#include "cp_usb_8910.h"
#include "bw0_usb_service.h"
#include "cp_transport_binding.h"
#include "osi_api.h"
#include "../capture/rxcapt_finite_abi.h"

static void barrier(void *context)
{
    (void)context;
    __asm__ volatile("dsb sy" ::: "memory");
}
static void clean(void *context,const volatile void *address,uint32_t bytes)
{
    (void)context;
    osiDCacheClean((const void *)address,bytes);
    barrier(0);
}
static void invalidate(void *context,const volatile void *address,uint32_t bytes)
{
    (void)context;
    osiDCacheInvalidate((const void *)address,bytes);
    barrier(0);
}
static uint32_t enter(void *context) { (void)context; return osiEnterCritical(); }
static void leave(void *context,uint32_t key) { (void)context; osiExitCritical(key); }
static void notify(void *context)
{
    struct cp_usb_8910 *s=context;
    if (s->wake) osiSemaphoreRelease(s->wake);
}
static int prepare_tx(void *context,uint32_t address,uint32_t bytes)
{
    (void)context;
    if (bytes!=RXCAPT_FINITE_DATA_BYTES || address<0x80960000u ||
        address-0x80960000u>=7u*RXCAPT_FINITE_DATA_BYTES ||
        (address-0x80960000u)%RXCAPT_FINITE_DATA_BYTES) return 0;
    /* AP never writes this read-only capture window. Discard cached old reads
     * and order DMA visibility; never clean AP's old cache over CP DMA data.
     * DATA slots are whole cache lines, with no metadata sharing.
     */
    osiDCacheInvalidate((const void *)(uintptr_t)address,bytes);
    barrier(0);
    return 1;
}
static struct cp_mailbox_cache cache(struct cp_usb_8910 *s)
{ return (struct cp_mailbox_cache){s,clean,invalidate,barrier}; }
static int snapshot(struct cp_usb_8910 *s,struct cp_capture_snapshot *value)
{
    return cp_capture_snapshot_read((volatile const uint32_t *)CP_USB_PROGRESS,
        (volatile const uint32_t *)CP_USB_EXPORT,CP_USB_GENERATION,cache(s),value);
}
int cp_usb_8910_final_scratch_drops(struct cp_usb_8910 *s,uint32_t *drops)
{
    if(!s || !drops || !s->prepared || s->mailbox.pending ||
       s->stream.phase!=CP_USB_DRAINED)return 0;
    return cp_capture_final_scratch_drops((volatile const uint32_t *)CP_USB_PROGRESS,
        (volatile const uint32_t *)CP_USB_EXPORT,CP_USB_GENERATION,cache(s),drops);
}
int cp_usb_8910_prepare(struct cp_usb_8910 *s,volatile uint32_t *lines)
{
    if (!s || s->prepared || (uintptr_t)lines!=CP_USB_MAILBOX) return 0;
    /* CP must still be idle: do not clear/reset a running mailbox. */
    invalidate(s,lines+8,32);
    for (unsigned i=0;i<16;++i) if (lines[i]) return 0;
    osiSemaphore_t *wake=osiSemaphoreCreate(1,0);
    if (!wake) return 0;
    if (!cp_stream_mailbox_init(&s->mailbox,lines,CP_USB_GENERATION,cache(s))) {
        osiSemaphoreDelete(wake); return 0;
    }
    clean(s,lines,32); /* publish zero request before activating the producer */
    s->wake=wake;
    s->prepared=1;
    return 1;
}
int cp_usb_8910_open(struct cp_usb_8910 *s,struct sdr_udc *udc,struct sdr_usb_ep *ep,uint32_t duration_ms)
{
    if (!s || !s->prepared || s->opened) return 0;
    struct cp_capture_snapshot value;
    if (!snapshot(s,&value)) return 0;
    uint32_t now=(uint32_t)osiUpTime();
    if (s->stream.phase==CP_USB_CLOSED && !cp_usb_stream_prepare(&s->stream,&s->mailbox,udc,ep,
        (struct iq_udc_platform){s,enter,leave,prepare_tx,notify},duration_ms)) return 0;
    if (s->stream.usb.udc!=udc || s->stream.usb.ep!=ep || s->stream.duration_ms!=duration_ms ||
        !cp_usb_stream_begin(&s->stream,value,now)) return 0;
    s->last_snapshot=value;
    s->last_snapshot_ms=now;
    s->opened=1;
    s->epoch_started=1;
    if(!s->session_clock_started) {
        s->session_started_ms=now; s->session_clock_started=1;
    }
    return 1;
}
int cp_usb_8910_session_expired(struct cp_usb_8910 *s,uint32_t now)
{
    if(s->session_lease_enabled) {
        /* The monitor can renew after the worker sampled now. A slightly
         * newer renewal is not a 2^32-ms absence; signed delta also covers
         * the uptime wrap while renewals remain within this short lease. */
        if((int32_t)(now-s->session_control_ms)>=5000) s->lease_expired=1;
        return s->lease_expired!=0;
    }
    return s->session_clock_started && s->session_duration_ms &&
        (uint32_t)(now-s->session_started_ms)>=s->session_duration_ms;
}
void cp_usb_8910_tick(struct cp_usb_8910 *s)
{
    if (!s || !s->prepared || (!s->opened && s->stream.phase!=CP_USB_FAULT)) return;
    uint32_t now=(uint32_t)osiUpTime();
    if (s->launch_result==2u && s->mailbox.operation==9u) {
        struct cp_stream_reply reply;
        /* An unresolved REARM cannot borrow the preceding epoch's STOP.
         * CP clears its old export before acknowledging operation 9. */
        if (!s->mailbox.pending || cp_stream_mailbox_poll(&s->mailbox,now,&reply)!=CP_MBOX_DONE)
            return;
        s->launch_result=1u;
    }
    struct cp_capture_snapshot value;
    if (snapshot(s,&value)) {
        s->last_snapshot=value; s->last_snapshot_ms=now;
        if((value.flags&1u) && !s->source_stop_seen) {
            s->source_stop_seen=1; s->source_stop_seen_ms=now;
        }
    } else {
        ++s->snapshot_misses;
        /* A launch timeout can precede the first valid snapshot. Do not
         * synthesize a generation/stop proof from a zero-initialized value.
         * A later valid stopped snapshot can still retire its UDC resources.
         */
        if (!s->opened && !s->last_snapshot.generation) return;
        if ((uint32_t)(now-s->last_snapshot_ms)>=1000u) cp_usb_stream_abort(&s->stream,7u);
    }
    /* A missed snapshot does not stop CP reply/UDC progress. The last valid
     * snapshot can be a readiness hint, never new proof of DMA teardown.
     */
    if(cp_usb_8910_session_expired(s,now)) s->stop_requested=1;
    if (s->stop_requested) cp_usb_stream_stop(&s->stream);
    cp_usb_stream_tick(&s->stream,&s->last_snapshot,now);
    cp_usb_scheduler_observe(&s->scheduler,s->mailbox.pending,s->mailbox.completed,osiUpTimeUS());
}
void cp_usb_8910_stop(struct cp_usb_8910 *s)
{
    if (!s) return;
    uint32_t key=osiEnterCritical();
    s->stop_requested=1;
    cp_usb_stream_stop(&s->stream);
    osiExitCritical(key);
    notify(s);
}
void cp_usb_8910_wait(struct cp_usb_8910 *s,uint32_t maximum_ms)
{
    if (!s || !s->wake) return;
    /* The vendor osiMsToOSTick rounds every positive millisecond timeout
     * up to a 20-ms tick (50 Hz). That exceeds the seven-slot BW0 budget
     * (~7.29 ms). Consume existing IRQ notifications without blocking;
     * otherwise yield through the SDK high-precision timer, not an RTOS
     * tick timeout. Default policy has no spin. The opt-in mailbox burst
     * skips sleep for at most eight polls and50us, then yields. No payload
     * access or ownership change is performed by the scheduler policy.
     * Actual wake latency still depends on the scheduler and is measured
     * by the hardware capture, not guaranteed by this requested interval.
     */
    uint32_t notified=osiSemaphoreTryAcquire(s->wake,0);
    uint64_t before=notified || !maximum_ms?0:osiUpTimeUS();
    uint32_t delay=cp_usb_scheduler_wait(&s->scheduler,notified,maximum_ms!=0,s->mailbox.pending,before);
    if(!delay)return;
    osiThreadSleepUS(delay);
    cp_usb_scheduler_slept(&s->scheduler,osiUpTimeUS()-before);
}
int cp_usb_8910_dispose(struct cp_usb_8910 *s)
{
    if (!s || !s->prepared || s->stream.usb.opened || s->mailbox.pending ||
        (s->launch_attempted && s->launch_result!=0 && !s->stream.cp_stopped) ||
        (s->opened && s->stream.phase!=CP_USB_DRAINED && s->stream.phase!=CP_USB_FAULT)) return 0;
    osiSemaphoreDelete(s->wake);
    s->wake=0; s->prepared=0; s->opened=0;
    /* Preserve stream/CP state: no implicit restart of the held RF service. */
    return 1;
}
static uint32_t run_prepared(struct cp_usb_8910 *s,struct sdr_udc *udc,struct sdr_usb_ep *ep,uint32_t duration_ms)
{
    uint32_t begun=(uint32_t)osiUpTime();
    while (!cp_usb_8910_open(s,udc,ep,duration_ms)) {
        if ((uint32_t)((uint32_t)osiUpTime()-begun)>=5000u) {
            s->run_error=12; cp_usb_stream_abort(&s->stream,12); return s->stream.phase;
        }
        cp_usb_8910_wait(s,1);
    }
    uint32_t fault_seen=0,fault_ms=0;
    for (;;) {
        cp_usb_8910_tick(s);
        if (s->stream.phase==CP_USB_DRAINED) return s->stream.phase;
        if (s->stream.phase==CP_USB_FAULT) {
            uint32_t now=(uint32_t)osiUpTime();
            if (!fault_seen) { fault_seen=1; fault_ms=now; }
            if ((!s->stream.usb.opened && !s->mailbox.pending) || now-fault_ms>=5000u)
                return s->stream.phase;
        }
        cp_usb_8910_wait(s,1);
    }
}
uint32_t cp_usb_8910_run(struct cp_usb_8910 *s,const struct cp_usb_8910_launch *launch)
{
    if (!s) return CP_USB_CLOSED;
    if (!launch || !launch->start || s->launch_attempted || s->prepared || s->opened ||
        s->stream.phase!=CP_USB_CLOSED) return s->stream.phase;
    s->run_error=0;
    if (!cp_usb_8910_prepare(s,launch->mailbox)) { s->run_error=8; return CP_USB_CLOSED; }
    if (!cp_usb_stream_prepare(&s->stream,&s->mailbox,launch->udc,launch->ep,
        (struct iq_udc_platform){s,enter,leave,prepare_tx,notify},launch->duration_ms)) {
        s->run_error=9; (void)cp_usb_8910_dispose(s); return CP_USB_CLOSED;
    }
    ++s->capture_epoch;
    s->launch_attempted=1;
    s->launch_result=(uint32_t)launch->start(launch->context);
    if (!s->launch_result) {
        /* A definitive refusal before submission owns no CP work. */
        s->run_error=10;
        (void)cp_usb_stream_unprepare(&s->stream);
        (void)cp_usb_8910_dispose(s);
        return s->stream.phase;
    }
    if (s->launch_result!=1u) {
        s->run_error=11; cp_usb_stream_abort(&s->stream,11); return s->stream.phase;
    }
    return run_prepared(s,launch->udc,launch->ep,launch->duration_ms);
}
#include "rf_profile.h"
uint32_t cp_usb_8910_restart(struct cp_usb_8910 *s,struct sdr_udc *udc,struct sdr_usb_ep *ep,
    uint32_t duration_ms,uint32_t raw_frequency,uint32_t gain_index,uint32_t channel)
{ return cp_usb_8910_restart_bw(s,udc,ep,duration_ms,raw_frequency,gain_index,channel,0); }
uint32_t cp_usb_8910_restart_bw(struct cp_usb_8910 *s,struct sdr_udc *udc,struct sdr_usb_ep *ep,
    uint32_t duration_ms,uint32_t raw_frequency,uint32_t gain_index,uint32_t channel,uint32_t bandwidth_index)
{
    if (!s) return CP_USB_CLOSED;
    if(s->stop_requested) return s->stream.phase;
    if (!s->prepared || !s->opened || s->stream.phase!=CP_USB_DRAINED ||
        !s->stream.cp_stopped || s->stream.usb.opened || s->mailbox.pending ||
        s->mailbox.fault || s->mailbox.completed>=UINT32_MAX-1u ||
        s->capture_epoch==UINT32_MAX ||
        !raw_frequency || !terminal_profile_raw_valid(channel,raw_frequency) || gain_index>124u ||
#if defined(SDR_EXPERIMENTAL_PRE_SWITCH) && SDR_EXPERIMENTAL_PRE_SWITCH
        bandwidth_index>7u ||
#else
        bandwidth_index>SDR_BW0_MAX_BW ||
#endif
        duration_ms>60000u) return s->stream.phase;
    struct cp_capture_snapshot stopped;
    if (!snapshot(s,&stopped) || stopped.phase!=30u || stopped.error ||
        !(stopped.flags&1u) || !stopped.dma_idle || stopped.published!=stopped.released)
    { s->run_error=15; return CP_USB_FAULT; }
    s->opened=s->epoch_started=0;
    s->stream=(struct cp_usb_stream){0};
    ++s->capture_epoch;
    s->source_stop_seen=s->source_stop_seen_ms=0;
    s->opened=0; s->run_error=0; s->snapshot_misses=0;
    s->last_snapshot=(struct cp_capture_snapshot){0};
    if (!cp_usb_stream_prepare(&s->stream,&s->mailbox,udc,ep,
        (struct iq_udc_platform){s,enter,leave,prepare_tx,notify},duration_ms)) {
        s->run_error=9; return s->stream.phase;
    }
    uint32_t packed=channel|(gain_index<<19);
#if defined(SDR_EXPERIMENTAL_FEM_OVERRIDE) && SDR_EXPERIMENTAL_FEM_OVERRIDE
    if(s->fem_override_mode>2u || (s->fem_override_mode &&
        !((channel>=2400u && channel<=2649u) || (channel>=3450u && channel<=3799u)))) {
        s->run_error=17; cp_usb_stream_abort(&s->stream,17); return s->stream.phase;
    }
    packed|=s->fem_override_mode<<26;
#endif
#if defined(SDR_EXPERIMENTAL_PRE_SWITCH) && SDR_EXPERIMENTAL_PRE_SWITCH
    if(bandwidth_index>=5u) packed|=(5u<<16)|(bandwidth_index<<26);
    else packed|=bandwidth_index<<16;
#else
    packed|=bandwidth_index<<16;
#endif
    if (!cp_stream_mailbox_begin(&s->mailbox,13u,packed,(uint32_t)osiUpTime(),1000u)) {
        s->run_error=13; cp_usb_stream_abort(&s->stream,13); return s->stream.phase;
    }
    for (;;) {
        struct cp_stream_reply configured;
        enum cp_mailbox_result result=cp_stream_mailbox_poll(&s->mailbox,(uint32_t)osiUpTime(),&configured);
        if (result==CP_MBOX_DONE) break;
        if (result<0) { s->run_error=14; cp_usb_stream_abort(&s->stream,14); return s->stream.phase; }
        cp_usb_8910_wait(s,1);
    }
    if(cp_usb_8910_session_expired(s,(uint32_t)osiUpTime())) s->stop_requested=1;
    if(s->stop_requested) {
        /* CONFIG is acknowledged and the preceding RF epoch remains idle.
         * Cancel new USB reservations before REARM can start another RF job. */
        if(cp_usb_stream_unprepare(&s->stream)) {
            s->stream.phase=CP_USB_DRAINED; s->stream.cp_stopped=1; s->opened=1;
            s->last_snapshot=stopped; s->last_snapshot_ms=(uint32_t)osiUpTime();
        } else { s->run_error=16; cp_usb_stream_abort(&s->stream,16); }
        return s->stream.phase;
    }
    if (!cp_stream_mailbox_begin(&s->mailbox,9u,raw_frequency,(uint32_t)osiUpTime(),1000u)) {
        s->run_error=13; cp_usb_stream_abort(&s->stream,13); return s->stream.phase;
    }
    s->launch_result=2u;
    /* The old stop proof ceases to apply once REARM can be accepted. Never
     * free these requests using the previous epoch's stopped snapshot. */
    struct cp_stream_reply reply;
    for (;;) {
        enum cp_mailbox_result result=cp_stream_mailbox_poll(&s->mailbox,(uint32_t)osiUpTime(),&reply);
        if (result==CP_MBOX_DONE) { s->launch_result=1u; break; }
        if (result<0) {
            s->run_error=14; cp_usb_stream_abort(&s->stream,14); return s->stream.phase;
        }
        cp_usb_8910_wait(s,1);
    }
    return run_prepared(s,udc,ep,duration_ms);
}
