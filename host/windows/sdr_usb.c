#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0602
#include <windows.h>
#include <setupapi.h>
#include <winusb.h>
#include <stdlib.h>
#include <string.h>
#include "sdr_usb.h"

static const GUID interface_guid = {0x5d6bce91,0x4f8a,0x4d42,{0x9a,0x0d,0xa9,0xe6,0xf8,0xac,0x89,0x10}};
struct request { OVERLAPPED overlapped; unsigned char *buffer; int pending; };
struct sdr_usb {
    HANDLE device;
    WINUSB_INTERFACE_HANDLE usb;
    UCHAR pipe;
    USHORT mps;
    struct sdr_usb_options options;
    struct request *request;
};

uint32_t sdr_usb_find(wchar_t *path, uint32_t characters)
{
    HDEVINFO devices=SetupDiGetClassDevsW(&interface_guid,NULL,NULL,DIGCF_PRESENT|DIGCF_DEVICEINTERFACE);
    if(devices==INVALID_HANDLE_VALUE) return GetLastError();
    SP_DEVICE_INTERFACE_DATA interface_data;
    memset(&interface_data,0,sizeof(interface_data));
    interface_data.cbSize=sizeof(interface_data);
    DWORD result=ERROR_NO_MORE_ITEMS;
    if(SetupDiEnumDeviceInterfaces(devices,NULL,&interface_guid,0,&interface_data)) {
        DWORD required=0;
        SetupDiGetDeviceInterfaceDetailW(devices,&interface_data,NULL,0,&required,NULL);
        PSP_DEVICE_INTERFACE_DETAIL_DATA_W detail=malloc(required);
        if(!detail) result=ERROR_NOT_ENOUGH_MEMORY;
        else {
            detail->cbSize=sizeof(*detail);
            if(!SetupDiGetDeviceInterfaceDetailW(devices,&interface_data,detail,required,NULL,NULL)) result=GetLastError();
            else if(wcslen(detail->DevicePath)+1>characters) result=ERROR_INSUFFICIENT_BUFFER;
            else { wcscpy(path,detail->DevicePath); result=0; }
            free(detail);
        }
    } else result=GetLastError();
    SetupDiDestroyDeviceInfoList(devices);
    return result;
}

void sdr_usb_close(sdr_usb *s)
{
    if(!s) return;
    if(s->usb) {
        WinUsb_AbortPipe(s->usb,s->pipe);
        if(s->request) for(uint32_t i=0;i<s->options.requests;++i) {
            if(s->request[i].pending) {
                ULONG actual;
                /* Do not free an OVERLAPPED/buffer until its request ends. */
                WinUsb_GetOverlappedResult(s->usb,&s->request[i].overlapped,&actual,TRUE);
                s->request[i].pending=0;
            }
        }
    }
    if(s->request) for(uint32_t i=0;i<s->options.requests;++i) {
        if(s->request[i].overlapped.hEvent) CloseHandle(s->request[i].overlapped.hEvent);
        if(s->request[i].buffer) VirtualFree(s->request[i].buffer,0,MEM_RELEASE);
    }
    free(s->request);
    if(s->usb) WinUsb_Free(s->usb);
    if(s->device!=INVALID_HANDLE_VALUE) CloseHandle(s->device);
    free(s);
}

uint32_t sdr_usb_open(sdr_usb **result,const wchar_t *path,struct sdr_usb_options options)
{
    if(!result || !path || options.requests<1 || options.requests>32 ||
        options.request_bytes<512 || options.request_bytes>4*1024*1024 || options.raw_io>1)
        return ERROR_INVALID_PARAMETER;
    *result=NULL;
    sdr_usb *s=calloc(1,sizeof(*s));
    if(!s) return ERROR_NOT_ENOUGH_MEMORY;
    s->device=INVALID_HANDLE_VALUE;
    s->options=options;
    DWORD error=0;
    s->device=CreateFileW(path,GENERIC_READ|GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,NULL,
        OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OVERLAPPED,NULL);
    if(s->device==INVALID_HANDLE_VALUE) { error=GetLastError(); goto failed; }
    if(!WinUsb_Initialize(s->device,&s->usb)) { error=GetLastError(); goto failed; }
    USB_INTERFACE_DESCRIPTOR descriptor;
    if(!WinUsb_QueryInterfaceSettings(s->usb,0,&descriptor)) { error=GetLastError(); goto failed; }
    if(descriptor.bInterfaceClass!=0xff || descriptor.bInterfaceSubClass!=0x53 ||
        descriptor.bInterfaceProtocol!=0x44 || descriptor.bNumEndpoints!=1) {
        error=ERROR_BAD_DEVICE; goto failed;
    }
    WINUSB_PIPE_INFORMATION pipe;
    if(!WinUsb_QueryPipe(s->usb,0,0,&pipe)) { error=GetLastError(); goto failed; }
    if(pipe.PipeType!=UsbdPipeTypeBulk || !(pipe.PipeId&0x80) || pipe.MaximumPacketSize!=512) {
        error=ERROR_BAD_DEVICE; goto failed;
    }
    s->pipe=pipe.PipeId;
    s->mps=pipe.MaximumPacketSize;
    if(options.request_bytes%s->mps) { error=ERROR_INVALID_PARAMETER; goto failed; }
    ULONG maximum=0,length=sizeof(maximum);
    if(!WinUsb_GetPipePolicy(s->usb,s->pipe,MAXIMUM_TRANSFER_SIZE,&length,&maximum)) {
        error=GetLastError(); goto failed;
    }
    if(options.request_bytes>maximum) { error=ERROR_INVALID_PARAMETER; goto failed; }
    UCHAR raw=(UCHAR)options.raw_io;
    if(!WinUsb_SetPipePolicy(s->usb,s->pipe,RAW_IO,sizeof(raw),&raw)) { error=GetLastError(); goto failed; }
    s->request=calloc(options.requests,sizeof(*s->request));
    if(!s->request) { error=ERROR_NOT_ENOUGH_MEMORY; goto failed; }
    for(uint32_t i=0;i<options.requests;++i) {
        s->request[i].overlapped.hEvent=CreateEventW(NULL,TRUE,FALSE,NULL);
        s->request[i].buffer=VirtualAlloc(NULL,options.request_bytes,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
        if(!s->request[i].overlapped.hEvent || !s->request[i].buffer) { error=GetLastError(); goto failed; }
    }
    *result=s;
    return 0;
failed:
    sdr_usb_close(s);
    return error;
}

static DWORD submit(sdr_usb *s,struct request *request)
{
    ResetEvent(request->overlapped.hEvent);
    BOOL done=WinUsb_ReadPipe(s->usb,s->pipe,request->buffer,s->options.request_bytes,NULL,&request->overlapped);
    DWORD error=done?0:GetLastError();
    if(error && error!=ERROR_IO_PENDING) return error;
    request->pending=1;
    if(done) SetEvent(request->overlapped.hEvent);
    return 0;
}
static uint64_t filetime(FILETIME time)
{ return ((uint64_t)time.dwHighDateTime<<32)|time.dwLowDateTime; }
static double cpu_seconds(void)
{
    FILETIME created,exited,kernel,user;
    if(!GetProcessTimes(GetCurrentProcess(),&created,&exited,&kernel,&user)) return 0;
    return (filetime(kernel)+filetime(user))*1e-7;
}
uint32_t sdr_usb_receive(sdr_usb *s,uint32_t duration_ms,sdr_usb_consumer consumer,void *context,
                         struct sdr_usb_stats *stats)
{
    return sdr_usb_receive_ready(s,duration_ms,consumer,context,stats,NULL,NULL);
}
uint32_t sdr_usb_receive_ready(sdr_usb *s,uint32_t duration_ms,sdr_usb_consumer consumer,void *context,
                         struct sdr_usb_stats *stats,sdr_usb_ready ready,void *ready_context)
{
    return sdr_usb_receive_controlled(s,duration_ms,consumer,context,stats,ready,ready_context,NULL,NULL);
}
uint32_t sdr_usb_receive_controlled(sdr_usb *s,uint32_t duration_ms,sdr_usb_consumer consumer,void *context,
                         struct sdr_usb_stats *stats,sdr_usb_ready ready,void *ready_context,
                         sdr_usb_stop_requested stop_requested,void *stop_context)
{
    if(!stats) return ERROR_INVALID_PARAMETER;
    memset(stats,0,sizeof(*stats));
    if(!s || (!duration_ms && !stop_requested) || duration_ms>120000) {
        stats->win32_error=ERROR_INVALID_PARAMETER;
        return ERROR_INVALID_PARAMETER;
    }
    stats->pipe_id=s->pipe; stats->maximum_packet_bytes=s->mps;
    LARGE_INTEGER frequency,begun,now;
    QueryPerformanceFrequency(&frequency);
    QueryPerformanceCounter(&begun);
    double cpu_start=cpu_seconds();
    DWORD error=0;
    int consumer_stopped=0;
    for(uint32_t i=0;i<s->options.requests;++i) {
        error=submit(s,&s->request[i]);
        if(error) break;
    }
    if(!error && ready) ready(ready_context);
    uint32_t next=0;
    while(!error) {
        if(stop_requested && stop_requested(stop_context)) break;
        QueryPerformanceCounter(&now);
        if(duration_ms && (double)(now.QuadPart-begun.QuadPart)*1000/frequency.QuadPart>=duration_ms) break;
        struct request *request=&s->request[next];
        DWORD wait=WaitForSingleObject(request->overlapped.hEvent,25);
        if(wait==WAIT_TIMEOUT) continue;
        if(wait!=WAIT_OBJECT_0) { error=GetLastError(); break; }
        ULONG actual=0;
        if(!WinUsb_GetOverlappedResult(s->usb,&request->overlapped,&actual,FALSE)) {
            error=GetLastError(); request->pending=0; break;
        }
        request->pending=0;
        ++stats->completions;
        stats->bytes+=actual;
        if(actual<s->options.request_bytes) ++stats->short_reads;
        if(!actual) ++stats->zero_reads;
        if(actual && consumer && consumer(request->buffer,actual,context)) {
            consumer_stopped=1;
            break;
        }
        error=submit(s,request);
        next=(next+1)%s->options.requests;
    }
    /* Stop issuing reads. Cancellation can race successful completion: deliver
     * those successes in submission order, rather than silently losing the tail.
     * A consumer that requested stop must never be called again. */
    WinUsb_AbortPipe(s->usb,s->pipe);
    for(uint32_t i=0;i<s->options.requests;++i) {
        struct request *request=&s->request[(next+i)%s->options.requests];
        if(!request->pending) continue;
        ULONG actual=0;
        BOOL completed=WinUsb_GetOverlappedResult(s->usb,&request->overlapped,&actual,TRUE);
        DWORD tail_error=completed?0:GetLastError();
        request->pending=0;
        if(completed && !error && !consumer_stopped) {
            ++stats->completions;
            stats->bytes+=actual;
            if(actual<s->options.request_bytes) ++stats->short_reads;
            if(!actual) ++stats->zero_reads;
            if(actual && consumer && consumer(request->buffer,actual,context))
                consumer_stopped=1;
        } else if(tail_error && tail_error!=ERROR_OPERATION_ABORTED && !error) {
            error=tail_error;
        }
    }
    QueryPerformanceCounter(&now);
    stats->elapsed_seconds=(double)(now.QuadPart-begun.QuadPart)/frequency.QuadPart;
    stats->process_cpu_seconds=cpu_seconds()-cpu_start;
    stats->win32_error=error;
    return error;
}
