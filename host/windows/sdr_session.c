#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string.h>
#include "sdr_session.h"

struct session {
    sdr_control *control;
    struct sdr_session_result *result;
    struct sdr_session_telemetry *telemetry;
    HANDLE ready;
    volatile LONG cancel, done;
    uint32_t duration;
    sdr_usb_consumer consumer;
    void *consumer_context;
    sdr_usb_stop_requested stop;
    void *stop_context;
    int consumer_stopped;
};
static int drained(struct sdr_session_result *r)
{
    return r->status[3]==4 && r->status[37] &&
        r->status[34]==r->status[35] && !r->recovery[7];
}
static uint32_t snapshot(struct session *s)
{
    struct sdr_session_result *r=s->result;
    uint32_t e=sdr_control_status(s->control,r->status);
    if(!e) e=sdr_control_recovery(s->control,r->recovery);
    if(!e && r->status[5]!=r->recovery[2]) e=ERROR_INVALID_DATA;
    return e;
}
static void observe(struct session *s)
{
    struct sdr_session_telemetry *t=s->telemetry;
    const uint32_t *w=s->result->status;
    uint32_t ms=w[46];uint64_t bytes=(uint64_t)w[22]+((uint64_t)w[23]<<32);
    if(!t || w[5]!=s->result->epoch || w[3]!=3 || ms<500 || (s->duration && ms+250u>=s->duration)) return;
    if(t->points) {
        if(ms<t->last_ms || bytes<t->last_bytes) { t->counter_invalid=1;return; }
        if(ms==t->last_ms) return;
        double rate=(double)(bytes-t->last_bytes)*1000/(ms-t->last_ms);
        if(t->points==1 || rate<t->minimum_window_bytes_per_second) t->minimum_window_bytes_per_second=rate;
        if(rate>t->maximum_window_bytes_per_second) t->maximum_window_bytes_per_second=rate;
    } else { t->first_ms=ms;t->first_bytes=bytes; }
    ++t->points;t->last_ms=ms;t->last_bytes=bytes;
}
static uint32_t release_held(sdr_control *control)
{
    uint32_t status[48],recovery[24],e=sdr_control_status(control,status);
    if(e) return e;
    e=sdr_control_recovery(control,recovery);
    if(e) return e;
    /* Never interrupt a live capture; only release an already drained lease. */
    if(status[3]!=4 || !status[37] || status[34]!=status[35] || recovery[7]) return 0;
    e=sdr_control_stop(control);
    if(e) return e;
    ULONGLONG deadline=GetTickCount64()+5000u;
    do {
        e=sdr_control_status(control,status);
        if(e) return e;
        e=sdr_control_recovery(control,recovery);
        if(e) return e;
        if(status[3]==4 && status[37] && status[34]==status[35] && !recovery[7]) return 0;
        Sleep(20);
    } while(GetTickCount64()<deadline);
    return ERROR_TIMEOUT;
}
static DWORD WINAPI control_thread(void *context)
{
    struct session *s=context;
    struct sdr_session_result *r=s->result;
    WaitForSingleObject(s->ready,INFINITE);
    if(InterlockedCompareExchange(&s->cancel,0,0)) goto done;
    r->control_error=sdr_control_start(s->control,s->duration,&r->epoch);
    ULONGLONG deadline=GetTickCount64()+s->duration+20000u;
    ULONGLONG next_poll=0;
    while(!r->control_error) {
        if(InterlockedCompareExchange(&s->cancel,0,0)) break;
        ULONGLONG now=GetTickCount64();
        if(now<next_poll) { Sleep(20);continue; }
        next_poll=now+200u;
        if(!s->duration) {
            r->control_error=sdr_control_keepalive(s->control);
            if(r->control_error) break;
        }
        r->control_error=snapshot(s);
        if(r->control_error) break;
        if(r->status[5]==r->epoch) {
            observe(s);
            if(r->status[4] || r->status[3]==5) {
                r->control_error=ERROR_GEN_FAILURE;break;
            }
            if(drained(r)) {
                r->device_drained=1;
                if(!s->duration) r->control_error=ERROR_OPERATION_ABORTED;
                if(!s->duration) goto done;
                /* A finite START can self-drain without releasing the held
                 * service lease.  Always perform the explicit STOP/drain
                 * handshake before returning so the next session is usable. */
                goto cleanup;
            }
        }
        if(s->duration && GetTickCount64()>=deadline) { r->control_error=ERROR_TIMEOUT;break; }
        Sleep(20);
    }
cleanup:
    /* START errors and finite self-drain both require an explicit STOP. Keep USB
     * reads running throughout cleanup so device USB completions can drain. */
    r->cleanup_error=sdr_control_stop(s->control);
    deadline=GetTickCount64()+10000u;
    do {
        uint32_t e=snapshot(s);
        if(e) { if(!r->cleanup_error) r->cleanup_error=e;break; }
        if(drained(r) && (!r->epoch || r->status[5]==r->epoch)) {
            r->device_drained=1;break;
        }
        Sleep(20);
    } while(GetTickCount64()<deadline);
    if(!r->device_drained && !r->cleanup_error) r->cleanup_error=ERROR_TIMEOUT;
done:
    InterlockedExchange(&s->done,1);
    return 0;
}
static void ready(void *context) { SetEvent(((struct session *)context)->ready); }
static int stop(void *context)
{
    struct session *s=context;
    if(s->stop && s->stop(s->stop_context)) InterlockedExchange(&s->cancel,1);
    return InterlockedCompareExchange(&s->done,0,0)!=0;
}
static int consume(const void *data,uint32_t bytes,void *context)
{
    struct session *s=context;
    if(s->consumer_stopped) s->result->discarded_after_consumer_stop+=bytes;
    else if(s->consumer && s->consumer(data,bytes,s->consumer_context)) {
        s->consumer_stopped=1;InterlockedExchange(&s->cancel,1);
    }
    return 0;
}
uint32_t sdr_session_receive(sdr_usb *usb,sdr_control *control,uint32_t band,
    uint32_t frequency,uint32_t gain,uint32_t duration,sdr_usb_consumer consumer,
    void *consumer_context,sdr_usb_stop_requested requested,void *stop_context,
    struct sdr_session_result *result)
{ return sdr_session_receive_bw(usb,control,band,frequency,gain,0,duration,consumer,consumer_context,requested,stop_context,result); }
uint32_t sdr_session_receive_bw(sdr_usb *usb,sdr_control *control,uint32_t band,
    uint32_t frequency,uint32_t gain,uint32_t bandwidth,uint32_t duration,sdr_usb_consumer consumer,
    void *consumer_context,sdr_usb_stop_requested requested,void *stop_context,
    struct sdr_session_result *result)
{ return sdr_session_receive_observed(usb,control,band,frequency,gain,bandwidth,duration,consumer,consumer_context,requested,stop_context,result,NULL); }
uint32_t sdr_session_receive_observed(sdr_usb *usb,sdr_control *control,uint32_t band,
    uint32_t frequency,uint32_t gain,uint32_t bandwidth,uint32_t duration,sdr_usb_consumer consumer,
    void *consumer_context,sdr_usb_stop_requested requested,void *stop_context,
    struct sdr_session_result *result,struct sdr_session_telemetry *telemetry)
{
    if(telemetry) memset(telemetry,0,sizeof(*telemetry));
    if(!result) return ERROR_INVALID_PARAMETER;
    memset(result,0,sizeof(*result));
    if(!usb || !control || (!duration && !requested && !consumer) ||
       (duration && duration<100) || duration>60000 || bandwidth>SDR_HOST_MAX_BANDWIDTH_INDEX)
        return result->control_error=ERROR_INVALID_PARAMETER;
    char info[SDR_CONTROL_MAX_PAYLOAD];uint32_t bytes=sizeof(info);
    uint32_t e=sdr_control_request(control,1,NULL,0,info,&bytes);
    if(!e && !band) {
        uint32_t status[48];e=sdr_control_status(control,status);
        if(!e)e=sdr_session_auto_route(info,bytes,frequency,status[40]>>8,bandwidth,!duration,&band);
    }
    if(!e) e=duration?sdr_session_validate_info_bw(info,bytes,band,bandwidth):
        sdr_session_validate_until_stop_info(info,bytes,band,bandwidth);
    if(e) return result->control_error=e;
    e=release_held(control);
    if(e) return result->control_error=e;
    e=sdr_control_configure_bw(control,band,frequency,gain,bandwidth);
    if(e) return result->control_error=e;
    e=sdr_control_status(control,result->status);
    if(!e && ((result->status[40]>>8)!=band || result->status[47]!=frequency ||
              result->status[45]!=gain || ((result->status[40]>>4)&7u)!=bandwidth ||
              result->status[9]!=sdr_nominal_sample_rate(bandwidth))) e=ERROR_INVALID_DATA;
    if(e) return result->control_error=e;
    struct session s={0};s.control=control;s.result=result;s.duration=duration;s.telemetry=telemetry;
    s.consumer=consumer;s.consumer_context=consumer_context;s.stop=requested;s.stop_context=stop_context;
    s.ready=CreateEventW(NULL,TRUE,FALSE,NULL);
    if(!s.ready) return result->control_error=GetLastError();
    HANDLE thread=CreateThread(NULL,0,control_thread,&s,0,NULL);
    if(!thread) { e=GetLastError();CloseHandle(s.ready);return result->control_error=e; }
    /* Control owns the session deadline and STOP/drain. Do not impose a
     * second USB lifetime that can cancel pending reads before that drain. */
    e=sdr_usb_receive_controlled(usb,0,consume,&s,&result->usb,ready,&s,stop,&s);
    /* Also wakes a thread when initial USB submissions failed before ready. */
    InterlockedExchange(&s.cancel,1);SetEvent(s.ready);
    WaitForSingleObject(thread,INFINITE);
    CloseHandle(thread);CloseHandle(s.ready);
    if(e) return e;
    if(result->control_error) return result->control_error;
    if(result->cleanup_error) return result->cleanup_error;
    return result->device_drained?0:ERROR_OPERATION_ABORTED;
}
