/* Host-observed stop/drain/config/start latency on the unchanged receiver API.
 * No payload parsing/copy/hash, firmware mutation, RF TX or sample timestamps.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sdr_session.h"

struct observation {
    LARGE_INTEGER begin,first,last,stop,end;
    uint64_t consumer_bytes;
    uint32_t error,band,frequency;
    struct sdr_session_result result;
};
static LARGE_INTEGER clock_rate;
static double elapsed(LARGE_INTEGER a,LARGE_INTEGER b)
{ return (double)(b.QuadPart-a.QuadPart)*1000.0/clock_rate.QuadPart; }
static int consume(const void *data,uint32_t bytes,void *context)
{
    (void)data;
    struct observation *o=context;
    if(!bytes)return 0;
    QueryPerformanceCounter(&o->last);
    if(!o->first.QuadPart)o->first=o->last;
    o->consumer_bytes+=bytes;
    if(elapsed(o->first,o->last)>=500.0) { o->stop=o->last;return 1; }
    return 0;
}
static int expired(void *context)
{
    LARGE_INTEGER now;QueryPerformanceCounter(&now);
    return elapsed(((struct observation *)context)->begin,now)>=10000.0;
}
static int number(const char *s,uint32_t *value)
{
    char *end;errno=0;
    unsigned long long n=strtoull(s,&end,10);
    if(errno || !*s || *end || n>0xffffffffu)return 0;
    *value=(uint32_t)n;return 1;
}
int main(int argc,char **argv)
{
    if(argc!=8 && argc!=9) {
        fprintf(stderr,"Usage: sdr_tune_benchmark COMn band1 hz1 band2 hz2 BW rounds(1..8) [request-bytes]\n");return 2;
    }
    uint32_t bands[2],frequencies[2],bw,rounds,request_bytes=65536;
    if(strncmp(argv[1],"COM",3) || strlen(argv[1])<4 || strlen(argv[1])>31 ||
       strspn(argv[1]+3,"0123456789")!=strlen(argv[1]+3) ||
       !number(argv[2],bands) || !number(argv[3],frequencies) ||
       !number(argv[4],bands+1) || !number(argv[5],frequencies+1) ||
       !number(argv[6],&bw) || !number(argv[7],&rounds) || !sdr_nominal_sample_rate(bw) || !rounds || rounds>8 ||
       (argc==9 && !number(argv[8],&request_bytes)) || request_bytes<512 ||
       request_bytes>4u*1024u*1024u || request_bytes%512u) return 2;
    wchar_t port[32],path[1024];
    for(unsigned i=0;i<=strlen(argv[1]);++i)port[i]=(wchar_t)argv[1][i];
    struct observation observations[16]={0};
    sdr_usb *usb=NULL;sdr_control *control=NULL;
    struct sdr_usb_options options={request_bytes,32,0};
    uint32_t error=sdr_usb_find(path,1024),count=0;
    if(!error)error=sdr_usb_open(&usb,path,options);
    if(!error)error=sdr_control_open(&control,port,5000);
    QueryPerformanceFrequency(&clock_rate);
    for(uint32_t i=0;!error && i<rounds*2;++i) {
        struct observation *o=observations+i;
        o->band=bands[i%2];o->frequency=frequencies[i%2];
        QueryPerformanceCounter(&o->begin);
        error=o->error=sdr_session_receive_bw(usb,control,o->band,o->frequency,40,bw,0,
            consume,o,expired,o,&o->result);
        QueryPerformanceCounter(&o->end);++count;
        if(!error && (!o->first.QuadPart || !o->stop.QuadPart || !o->result.device_drained ||
            o->result.status[3]!=4 || o->result.status[4] || !o->result.status[37] ||
            o->result.status[40]>>8!=o->band || o->result.status[47]!=o->frequency ||
            o->result.status[45]!=40 || ((o->result.status[40]>>4)&7)!=bw))
            error=o->error=ERROR_INVALID_DATA;
    }
    /* Session API owns STOP/drain even on errors. Never borrow a successful
     * previous terminal as proof that a failed next session is safe to reuse. */
    sdr_control_close(control);sdr_usb_close(usb);
    printf("{\"status\":\"%s\",\"error\":%u,\"bandwidth_index\":%u,\"rounds\":%u,"
        "\"host_qpc_frequency\":%lld,\"sample_timestamps\":false,\"same_handles_reused\":true,"
        "\"requested_delivery_window_ms\":500,\"request_bytes\":%u,\"nominal_sample_rate_hz\":%u,\"sessions\":[",
        error?"failed":"passed",error,bw,rounds,clock_rate.QuadPart,request_bytes,sdr_nominal_sample_rate(bw));
    for(uint32_t i=0;i<count;++i) {
        struct observation *o=observations+i;struct sdr_session_result *r=&o->result;
        double gap=(i && o->first.QuadPart && observations[i-1].last.QuadPart)?
            elapsed(observations[i-1].last,o->first):0;
        printf("%s{\"band\":%u,\"frequency_hz\":%u,\"error\":%u,\"epoch\":%u,"
            "\"begin_qpc\":%lld,\"first_delivery_qpc\":%lld,\"last_delivery_qpc\":%lld,"
            "\"stop_requested_qpc\":%lld,\"return_qpc\":%lld,"
            "\"call_to_first_delivery_ms\":%.6f,\"stop_to_return_ms\":%.6f,\"previous_delivery_gap_ms\":%.6f,"
            "\"delivered_bytes\":%llu,\"usb_bytes\":%llu,\"drain_discarded_bytes\":%llu,"
            "\"device_drained\":%u,\"device_full_stops\":%u,\"device_observed_gap_ms\":%llu,"
            "\"control_error\":%u,\"cleanup_error\":%u}",i?",":"",o->band,o->frequency,o->error,r->epoch,
            o->begin.QuadPart,o->first.QuadPart,o->last.QuadPart,o->stop.QuadPart,o->end.QuadPart,
            o->first.QuadPart?elapsed(o->begin,o->first):0,o->stop.QuadPart?elapsed(o->stop,o->end):0,gap,
            (unsigned long long)o->consumer_bytes,(unsigned long long)r->usb.bytes,
            (unsigned long long)r->discarded_after_consumer_stop,r->device_drained,r->recovery[4],
            (unsigned long long)r->recovery[8]+((unsigned long long)r->recovery[9]<<32),r->control_error,r->cleanup_error);
    }
    puts("]}");return error?1:0;
}
