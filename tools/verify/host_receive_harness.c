#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0602
#include <windows.h>
#include <winusb.h>
#include <assert.h>
#include <stdio.h>

static unsigned submissions,ready_calls,results,abort_calls,fail_at,consumed;
static int tail_mode;
static int virtual_clock;
static LONGLONG virtual_ticks;
static BOOL WINAPI simulated_counter(LARGE_INTEGER *counter)
{
    if(!virtual_clock) return QueryPerformanceCounter(counter);
    LARGE_INTEGER frequency;QueryPerformanceFrequency(&frequency);
    counter->QuadPart=virtual_ticks;virtual_ticks+=200*frequency.QuadPart;
    return TRUE;
}
static OVERLAPPED *pending[3];
static BOOL WINAPI fake_read(WINUSB_INTERFACE_HANDLE u,UCHAR pipe,PUCHAR data,ULONG size,
                            PULONG actual,LPOVERLAPPED ov)
{
    (void)u;(void)pipe;(void)data;(void)size;(void)actual;
    ++submissions;
    if (submissions==fail_at) { SetLastError(ERROR_DEVICE_NOT_CONNECTED); return FALSE; }
    pending[submissions-1]=ov;
    SetLastError(ERROR_IO_PENDING); return FALSE;
}
static BOOL WINAPI fake_result(WINUSB_INTERFACE_HANDLE u,LPOVERLAPPED ov,PULONG actual,BOOL wait)
{
    (void)u;(void)wait; ++results;
    if(tail_mode && ov==pending[2]) {
        SetLastError(ERROR_OPERATION_ABORTED); return FALSE;
    }
    *actual=512; return TRUE;
}
static BOOL WINAPI fake_abort(WINUSB_INTERFACE_HANDLE u,UCHAR pipe)
{ (void)u;(void)pipe; ++abort_calls; return TRUE; }
#define WinUsb_ReadPipe fake_read
#define WinUsb_GetOverlappedResult fake_result
#define WinUsb_AbortPipe fake_abort
#define QueryPerformanceCounter simulated_counter
#include "../../host/windows/sdr_usb.c"

static void ready(void *context)
{
    assert(context==pending && submissions==3 && !results && !fail_at);
    ++ready_calls;
    for (unsigned i=0;i<3;++i) SetEvent(pending[i]->hEvent);
    if(tail_mode) Sleep(20); /* Deadline occurs before the first consumption. */
}
static int consume(const void *bytes,uint32_t length,void *context)
{
    assert(bytes && length==512 && context==pending && ready_calls==1);
    if(tail_mode) assert(*(const unsigned char *)bytes==consumed);
    ++consumed; return !tail_mode;
}
static int external_stop(void *context)
{ assert(context==pending && ready_calls==1); return 1; }
static int keep_reading(void *context)
{ assert(context==pending && ready_calls==1); return 0; }
int main(void)
{
    struct sdr_usb s={0};
    struct request requests[3]={0};
    unsigned char buffers[3][512]={{0}};
    struct sdr_usb_stats stats;
    s.options=(struct sdr_usb_options){512,3,0}; s.request=requests; s.pipe=0x86; s.mps=512;
    for (unsigned i=0;i<3;++i) {
        requests[i].buffer=buffers[i];
        requests[i].overlapped.hEvent=CreateEventW(NULL,TRUE,FALSE,NULL);
        assert(requests[i].overlapped.hEvent);
    }
    assert(!sdr_usb_receive_ready(&s,1000,consume,pending,&stats,ready,pending));
    assert(ready_calls==1 && consumed==1 && submissions==3 && results==3 && abort_calls==1);
    assert(stats.bytes==512 && stats.completions==1);
    submissions=ready_calls=consumed=results=abort_calls=0; fail_at=3;
    assert(sdr_usb_receive_ready(&s,1000,consume,pending,&stats,ready,pending)==ERROR_DEVICE_NOT_CONNECTED);
    assert(!ready_calls && !consumed && submissions==3 && results==2 && abort_calls==1);
    submissions=ready_calls=consumed=results=abort_calls=fail_at=0;
    tail_mode=1;
    for(unsigned i=0;i<3;++i) buffers[i][0]=(unsigned char)i;
    assert(!sdr_usb_receive_ready(&s,1,consume,pending,&stats,ready,pending));
    assert(consumed==2 && results==3 && abort_calls==1);
    assert(stats.bytes==1024 && stats.completions==2 && !stats.win32_error);
    for(unsigned i=0;i<3;++i) assert(!requests[i].pending);
    submissions=ready_calls=consumed=results=abort_calls=0;
    assert(!sdr_usb_receive_controlled(&s,120000,consume,pending,&stats,ready,pending,external_stop,pending));
    assert(consumed==2 && stats.bytes==1024 && results==3 && abort_calls==1);
    assert(stats.elapsed_seconds<1.0); /* A terminal producer bypasses the duration fallback. */
    memset(&stats,0xa5,sizeof(stats));
    assert(sdr_usb_receive(&s,0,NULL,NULL,&stats)==ERROR_INVALID_PARAMETER);
    assert(!stats.bytes && !stats.completions && !stats.elapsed_seconds && stats.win32_error==ERROR_INVALID_PARAMETER);
    submissions=ready_calls=consumed=results=abort_calls=0;tail_mode=0;
    virtual_clock=1;virtual_ticks=0;
    /* More than120s elapses before the first event. Explicit-stop mode must
     * still deliver the input; the consumer then stops and tail ownership is
     * returned without invoking that consumer again. No real-time sleep. */
    assert(!sdr_usb_receive_controlled(&s,0,consume,pending,&stats,ready,pending,keep_reading,pending));
    assert(consumed==1 && stats.bytes==512 && stats.elapsed_seconds>=200);
    assert(results==3 && abort_calls==1);
    for(unsigned i=0;i<3;++i) assert(!requests[i].pending);
    for (unsigned i=0;i<3;++i) CloseHandle(requests[i].overlapped.hEvent);
    puts("passed: initial readiness; submission failure; consumer stop; external stop bypasses duration; explicit-stop read survives simulated200s without deadline; tail ownership returned once; ordered successes and cancelled tail; zero duration without controller rejected; stub WinUSB, native Windows events");
    return 0;
}
