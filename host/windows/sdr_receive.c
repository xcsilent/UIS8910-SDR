#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <io.h>
#include <fcntl.h>
#include "sdr_usb.h"
#include "sdr_session.h"
#include "file_sink.h"

static volatile LONG interrupted;
static BOOL WINAPI console_stop(DWORD event)
{
    if(event!=CTRL_C_EVENT && event!=CTRL_BREAK_EVENT) return FALSE;
    InterlockedExchange(&interrupted,1);return TRUE;
}
static uint32_t number(const char *text)
{
    char *end;errno=0;unsigned long value=strtoul(text,&end,10);
    if(!*text || *text=='-' || *text=='+' || *end || errno || value>UINT32_MAX) {
        fprintf(stderr,"invalid unsigned integer: %s\n",text);exit(2);
    }
    return (uint32_t)value;
}

struct file_sink { HANDLE file,stop_event; DWORD error; sdr_file_sink *async; uint64_t written; };
static int stdout_raw;
static int stop_requested(void *context)
{
    struct file_sink *sink=context;
    return InterlockedCompareExchange(&interrupted,0,0) ||
        (sink->stop_event && WaitForSingleObject(sink->stop_event,0)==WAIT_OBJECT_0) ||
        sdr_file_sink_error(sink->async)!=0;
}
static void reads_ready(void *context)
{
    (void)context;
    fprintf(stderr,"ready\n"); fflush(stderr);
}
static int write_raw(const void *data,uint32_t bytes,void *context)
{
    struct file_sink *sink=context;
    if(stdout_raw) {
        size_t n=fwrite(data,1,bytes,stdout);
        if(n!=bytes || fflush(stdout)==EOF) {
            sink->error=ERROR_WRITE_FAULT;return 1;
        }
        sink->written+=n;
        return 0;
    }
    if(sink->async) return sdr_file_sink_push(sink->async,data,bytes);
    DWORD written=0;
    if(!WriteFile(sink->file,data,bytes,&written,NULL)) { sink->error=GetLastError(); sink->written+=written; return 1; }
    sink->written+=written;
    if(written!=bytes) { sink->error=ERROR_WRITE_FAULT; return 1; }
    return 0;
}
int main(int argc,char **argv)
{
    uint32_t duration=15000;
    struct sdr_usb_options options={65536,32,0};
    const char *output=NULL;
    const char *stop_name=NULL;
    const char *port=NULL;
    uint32_t band=0,frequency=881500000,gain=40,bandwidth=0;
    int rf_options=0;
    int list=0,synchronous=0;
    uint32_t file_blocks=32;
    for(int i=1;i<argc;++i) {
        if(!strcmp(argv[i],"--list")) list=1;
        else if(!strcmp(argv[i],"--port") && i+1<argc) port=argv[++i];
        else if(!strcmp(argv[i],"--band") && i+1<argc) { const char *b=argv[++i];band=!strcmp(b,"auto")?0:number(b);rf_options=1; }
        else if(!strcmp(argv[i],"--frequency-hz") && i+1<argc) { frequency=number(argv[++i]);rf_options=1; }
        else if(!strcmp(argv[i],"--gain-index") && i+1<argc) { gain=number(argv[++i]);rf_options=1; }
        else if(!strcmp(argv[i],"--bandwidth-index") && i+1<argc) { bandwidth=number(argv[++i]);rf_options=1; }
        else if(!strcmp(argv[i],"--milliseconds") && i+1<argc) duration=number(argv[++i]);
        else if(!strcmp(argv[i],"--request-bytes") && i+1<argc) options.request_bytes=number(argv[++i]);
        else if(!strcmp(argv[i],"--requests") && i+1<argc) options.requests=number(argv[++i]);
        else if(!strcmp(argv[i],"--raw-io")) options.raw_io=1;
        else if(!strcmp(argv[i],"--output") && i+1<argc) output=argv[++i];
        else if(!strcmp(argv[i],"--sync-file")) synchronous=1;
        else if(!strcmp(argv[i],"--file-queue-blocks") && i+1<argc) file_blocks=number(argv[++i]);
        else if(!strcmp(argv[i],"--stop-event") && i+1<argc) stop_name=argv[++i];
        else if(!strcmp(argv[i],"--stdout-raw")) stdout_raw=1;
        else { fprintf(stderr,"usage: sdr_receive [--list] [--port COMn --band N --frequency-hz N --gain-index N] [--milliseconds N] [--request-bytes N] [--requests N] [--raw-io] [--stdout-raw] [--output FILE] [--sync-file] [--file-queue-blocks N] [--stop-event NAME]\n"); return 2; }
    }
    if((rf_options && !port) || (port && (list || (duration && duration<100) || duration>60000 || !frequency || frequency%100 || gain>124 || bandwidth>SDR_HOST_MAX_BANDWIDTH_INDEX))) {
        fprintf(stderr,"BW0 requires --port, duration 100..60000, frequency in 100 Hz units, gain 0..124\n");return 2;
    }
    if((!duration && !port) || duration>120000) {
        fprintf(stderr,"milliseconds must be in 1..120000\n"); return 2;
    }
    if(stdout_raw && (output || list)) {
        fprintf(stderr,"--stdout-raw cannot be combined with --output or --list\n");return 2;
    }
    if(stdout_raw && _setmode(_fileno(stdout),_O_BINARY)==-1) return 2;
    if(file_blocks<2 || file_blocks>256 || (uint64_t)file_blocks*options.request_bytes>256u*1024u*1024u) {
        fprintf(stderr,"file queue must have 2..256 blocks and at most 256 MiB\n");return 2;
    }
    wchar_t path[2048];
    DWORD error=sdr_usb_find(path,2048);
    if(error) { fprintf(stderr,"SDR WinUSB interface discovery failed: %lu\n",(unsigned long)error); return 1; }
    if(list) { wprintf(L"%ls\n",path); return 0; }
    sdr_usb *usb=NULL;
    error=sdr_usb_open(&usb,path,options);
    if(error) { fprintf(stderr,"SDR WinUSB open failed: %lu\n",(unsigned long)error); return 1; }
    struct file_sink sink={0};sink.file=INVALID_HANDLE_VALUE;
    HANDLE stop_event=NULL;
    if(stop_name) {
        stop_event=OpenEventA(SYNCHRONIZE,FALSE,stop_name);
        if(!stop_event) { error=GetLastError(); sdr_usb_close(usb); return (int)error; }
    }
    sink.stop_event=stop_event;
    if(output) {
        if(synchronous) {
            sink.file=CreateFileA(output,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
            error=sink.file==INVALID_HANDLE_VALUE?GetLastError():0;
        } else error=sdr_file_sink_open(&sink.async,output,options.request_bytes,file_blocks);
        if(error) { if(stop_event) CloseHandle(stop_event); sdr_usb_close(usb); return (int)error; }
    }
    struct sdr_usb_stats stats={0};
    struct sdr_session_result session={0};
    struct sdr_session_telemetry telemetry={0};
    SetConsoleCtrlHandler(console_stop,TRUE);
    if(port) {
        wchar_t control_port[40];sdr_control *control=NULL;
        if(!MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,port,-1,control_port,40)) error=ERROR_INVALID_PARAMETER;
        else error=sdr_control_open(&control,control_port,1000);
        if(!error) error=sdr_session_receive_observed(usb,control,band,frequency,gain,bandwidth,duration,
            (output || stdout_raw)?write_raw:NULL,&sink,stop_requested,&sink,&session,&telemetry);
        else session.control_error=error;
        sdr_control_close(control);stats=session.usb;
    } else error=sdr_usb_receive_controlled(usb,duration,(output || stdout_raw)?write_raw:NULL,&sink,&stats,reads_ready,NULL,
        stop_requested,&sink);
    SetConsoleCtrlHandler(console_stop,FALSE);
    sdr_usb_close(usb);
    int requested_stop=InterlockedCompareExchange(&interrupted,0,0)!=0 ||
        (stop_event && WaitForSingleObject(stop_event,0)==WAIT_OBJECT_0);
    if(stop_event) CloseHandle(stop_event);
    struct sdr_file_stats file_stats={0};
    if(output && !synchronous) sink.error=sdr_file_sink_close(&sink.async,&file_stats,3000);
    if(output && synchronous) {
        if(!CloseHandle(sink.file) && !sink.error) sink.error=GetLastError();
        file_stats.written_bytes=file_stats.queued_bytes=sink.written;
    }
    fprintf(stdout_raw?stderr:stdout,"{\"bytes\":%llu,\"completions\":%llu,\"short_reads\":%llu,\"zero_reads\":%llu,"
           "\"elapsed_seconds\":%.6f,\"process_cpu_seconds\":%.6f,\"win32_error\":%lu,\"file_error\":%lu,"
           "\"pipe_id\":%lu,\"request_bytes\":%lu,\"requests\":%lu,\"raw_io\":%lu,"
           "\"file_mode\":\"%s\",\"file_written_bytes\":%llu,\"file_queued_bytes\":%llu,"
           "\"file_dropped_bytes\":%llu,\"file_queue_full_events\":%llu,\"file_queue_high_water\":%lu,"
           "\"file_pending_blocks\":%lu,\"file_writer_alive\":%s,\"file_drain_seconds\":%.6f,"
           "\"file_writer_cpu_seconds\":%.6f",
           (unsigned long long)stats.bytes,(unsigned long long)stats.completions,
           (unsigned long long)stats.short_reads,(unsigned long long)stats.zero_reads,
           stats.elapsed_seconds,stats.process_cpu_seconds,(unsigned long)(port?stats.win32_error:error),(unsigned long)sink.error,
           (unsigned long)stats.pipe_id,(unsigned long)options.request_bytes,
           (unsigned long)options.requests,(unsigned long)options.raw_io,
           output?(synchronous?"synchronous":"queued"):"none",
           (unsigned long long)file_stats.written_bytes,(unsigned long long)file_stats.queued_bytes,
           (unsigned long long)file_stats.dropped_bytes,(unsigned long long)file_stats.queue_full_events,
           (unsigned long)file_stats.high_water_blocks,(unsigned long)file_stats.pending_blocks,
           sink.async?"true":"false",file_stats.drain_seconds,file_stats.writer_cpu_seconds);
    if(port) {
        fprintf(stdout_raw?stderr:stdout,",\"requested_band\":%u,\"auto_route\":%s",band,band?"false":"true");
        if(!band && session.epoch)band=session.status[40]>>8;
        fprintf(stdout_raw?stderr:stdout,",\"continuous_mode\":%s,\"stop_requested\":%s",duration?"false":"true",requested_stop?"true":"false");
        uint64_t device=(uint64_t)session.status[22]+((uint64_t)session.status[23]<<32);
        uint64_t gaps=(uint64_t)session.recovery[8]+((uint64_t)session.recovery[9]<<32);
        char count[32]="null",difference[32]="null";
        if(session.epoch && session.status[5]==session.epoch && session.recovery[2]==session.epoch) {
            snprintf(count,sizeof(count),"%llu",(unsigned long long)device);
            snprintf(difference,sizeof(difference),"%lld",(long long)device-(long long)stats.bytes);
        }
        fprintf(stdout_raw?stderr:stdout,",\"source\":\"bw0\",\"band\":%u,\"frequency_hz\":%u,\"gain_index\":%u,"
            "\"bandwidth_index\":%u,\"requested_nominal_sample_rate_hz\":%u,\"sample_rate_measured\":false,"
            "\"session_error\":%lu,\"control_error\":%u,\"control_device_status\":%u,\"cleanup_error\":%u,\"device_drained\":%s,\"epoch\":%u,"
            "\"device_completed_bytes\":%s,\"device_minus_host_bytes\":%s,"
            "\"discarded_after_consumer_stop\":%llu,\"full_ring_stops\":%u,"
            "\"observed_gap_ms\":%llu,\"lost_samples_known\":false,\"device_status\":[",
            band,frequency,gain,bandwidth,sdr_nominal_sample_rate(bandwidth),(unsigned long)error,session.control_error,
            (unsigned)(session.control_error&0x0fffffffu),session.cleanup_error,
            session.device_drained?"true":"false",session.epoch,count,difference,
            (unsigned long long)session.discarded_after_consumer_stop,
            session.recovery[4],(unsigned long long)gaps);
        for(unsigned i=0;i<48;++i) fprintf(stdout_raw?stderr:stdout,"%s%u",i?",":"",session.status[i]);
        fprintf(stdout_raw?stderr:stdout,"],\"recovery_status\":[");
        for(unsigned i=0;i<24;++i) fprintf(stdout_raw?stderr:stdout,"%s%u",i?",":"",session.recovery[i]);
        uint32_t window=telemetry.last_ms-telemetry.first_ms;
        int measured=telemetry.points>=3 && window>=1000 && !telemetry.counter_invalid;
        char rate[64]="null";
        if(measured) snprintf(rate,sizeof(rate),"%.3f",(double)(telemetry.last_bytes-telemetry.first_bytes)*1000/window);
        fprintf(stdout_raw?stderr:stdout,"],\"steady_device_rate_measured\":%s,\"steady_device_bytes_per_second\":%s,"
            "\"steady_device_window_ms\":%u,\"steady_device_samples\":%u,"
            "\"steady_device_counter_invalid\":%s,\"minimum_device_window_bytes_per_second\":%.3f,"
            "\"maximum_device_window_bytes_per_second\":%.3f,\"control_poll_period_ms\":200",
            measured?"true":"false",rate,window,telemetry.points,telemetry.counter_invalid?"true":"false",
            telemetry.minimum_window_bytes_per_second,telemetry.maximum_window_bytes_per_second);
    }
    fprintf(stdout_raw?stderr:stdout,"}\n");
    return error || sink.error ? 1:0;
}
