#include "cp_usb_stream.h"
#if SDR_USB_SEGMENT_PROFILE
#include "usb_segment_profile.h"
#endif
#ifndef CP_USB_COMBINED_EXCHANGE
#define CP_USB_COMBINED_EXCHANGE 0
#endif

static void fault(struct cp_usb_stream *s,uint32_t error)
{
    s->phase=CP_USB_FAULT;
    if (!s->error) s->error=error;
    uint32_t key=s->usb.platform.enter(s->usb.platform.context);
    cp_capture_bridge_fail(&s->bridge);
    s->usb.platform.leave(s->usb.platform.context,key);
}
static int send(struct cp_usb_stream *s,uint32_t operation,uint32_t block,uint32_t now)
{
    if (!cp_stream_mailbox_begin(s->mailbox,operation,block,now,1000u)) {
        fault(s,1); return 0;
    }
    ++s->commands;
#if SDR_USB_SEGMENT_PROFILE
    if(usb_refill_active() && (operation==12u || operation==14u) && block>s->bridge.released) {
        uint32_t key=s->usb.platform.enter(s->usb.platform.context);
        usb_refill_event(USB_REFILL_RELEASE,sdr_usb_profile_clock(),0);
        s->usb.platform.leave(s->usb.platform.context,key);
    }
#endif
    return 1;
}
int cp_usb_stream_prepare(struct cp_usb_stream *s,struct cp_stream_mailbox *mailbox,
    struct sdr_udc *udc,struct sdr_usb_ep *ep,struct iq_udc_platform platform,
    uint32_t duration_ms)
{
    if (!s || s->phase!=CP_USB_CLOSED || !mailbox || mailbox->pending || mailbox->fault ||
        duration_ms>60000u) return 0;
    *s=(struct cp_usb_stream){0};
    s->mailbox=mailbox; s->duration_ms=duration_ms;
    if (!cp_capture_bridge_init(&s->bridge,&s->ring,mailbox->generation) ||
        !iq_udc_open(&s->usb,&s->ring,udc,ep,platform)) return 0;
    s->phase=CP_USB_PREPARED;
    return 1;
}
int cp_usb_stream_begin(struct cp_usb_stream *s,struct cp_capture_snapshot initial,uint32_t now_ms)
{
    if (!s || s->phase!=CP_USB_PREPARED || !s->usb.opened || s->mailbox->pending || s->mailbox->fault ||
        initial.generation!=s->mailbox->generation || initial.released || initial.published>s->ring.slots ||
        initial.error) return 0;
    /* Seven slots may fill before AP observes the first RUNNING snapshot.
     * A verified stopped producer still owns valid queued data to drain.
     * No DMA idle proof => keep waiting rather than reuse any live storage. */
    int running=!initial.flags && initial.phase>=24u && initial.phase<=27u;
    int stopped=(initial.flags==1u || initial.flags==3u) && initial.phase==30u && initial.dma_idle;
    if(!running && !stopped) return 0;
    s->started_ms=now_ms; s->phase=CP_USB_RUNNING;
    return 1;
}
int cp_usb_stream_unprepare(struct cp_usb_stream *s)
{
    if (!s || s->phase!=CP_USB_PREPARED || s->mailbox->pending || !iq_udc_close(&s->usb)) return 0;
    s->phase=CP_USB_CLOSED;
    return 1;
}
int cp_usb_stream_open(struct cp_usb_stream *s,struct cp_stream_mailbox *mailbox,
    struct sdr_udc *udc,struct sdr_usb_ep *ep,struct iq_udc_platform platform,
    struct cp_capture_snapshot initial,uint32_t now_ms,uint32_t duration_ms)
{
    if (!cp_usb_stream_prepare(s,mailbox,udc,ep,platform,duration_ms)) return 0;
    if (cp_usb_stream_begin(s,initial,now_ms)) return 1;
    (void)cp_usb_stream_unprepare(s);
    return 0;
}
void cp_usb_stream_stop(struct cp_usb_stream *s)
{
    if (s && (s->phase==CP_USB_RUNNING || s->phase==CP_USB_PREPARED)) s->stop_requested=1;
}
void cp_usb_stream_abort(struct cp_usb_stream *s,uint32_t error)
{
    if (s && s->phase!=CP_USB_CLOSED && s->phase!=CP_USB_DRAINED) fault(s,error?error:7u);
}
void cp_usb_stream_tick(struct cp_usb_stream *s,const struct cp_capture_snapshot *snapshot,uint32_t now)
{
    if (!s || !snapshot || s->phase==CP_USB_CLOSED || s->phase==CP_USB_DRAINED || s->phase==CP_USB_PREPARED) return;
#if SDR_USB_SEGMENT_PROFILE
    if(usb_refill_active()) {
        uint32_t key=s->usb.platform.enter(s->usb.platform.context);
        if(s->phase!=CP_USB_RUNNING || s->stop_requested || (snapshot->flags&1u))
            usb_refill_end(0,sdr_usb_profile_clock());
        else {
            uint32_t context=(s->mailbox->pending?1u:0u) | (s->mailbox->operation<<8) |
                (snapshot->published>s->bridge.claimed?2u:0u);
            uint64_t at=sdr_usb_profile_clock();
            usb_refill_event(USB_REFILL_WORKER,at,context);
            if(snapshot->published>s->bridge.claimed)usb_refill_event(USB_REFILL_PUBLISHED,at,0);
        }
        s->usb.platform.leave(s->usb.platform.context,key);
    }
#endif
    if (snapshot->generation!=s->mailbox->generation) { fault(s,2); return; }
    if (snapshot->phase==30u || snapshot->phase==31u) {
        if ((snapshot->flags&1u) && snapshot->dma_idle) s->cp_stopped=1;
    }
    if (s->usb.terminal_error || snapshot->error || snapshot->phase==31u) fault(s,3);
    if (s->mailbox->pending) {
        uint32_t operation=s->mailbox->operation;
        struct cp_stream_reply reply;
        enum cp_mailbox_result result=cp_stream_mailbox_poll(s->mailbox,now,&reply);
        if (result<0) fault(s,4);
        else if (result==CP_MBOX_DONE && operation==7u) s->stop_accepted=1;
        else if (result==CP_MBOX_DONE && s->phase!=CP_USB_FAULT) {
            int ok=1;
            uint32_t key=s->usb.platform.enter(s->usb.platform.context);
#if SDR_USB_SEGMENT_PROFILE
            uint32_t release_before=s->bridge.released;
#endif
            if (operation==11u)
                ok=cp_capture_claim_commit(&s->bridge,s->mailbox->generation,reply.value0,reply.value1);
            else if (operation==12u)
                ok=cp_capture_release_commit(&s->bridge,s->mailbox->generation,reply.value1);
            else if(operation==14u) {
#if SDR_USB_SEGMENT_PROFILE
                uint32_t released=s->bridge.released,claimed=s->bridge.claimed;
#endif
                ok=cp_capture_exchange_commit(&s->bridge,s->mailbox->generation,reply.value0,reply.value1);
#if SDR_USB_SEGMENT_PROFILE
                if(ok)usb_segment_profile_exchange(reply.value0-released,reply.value1-claimed);
#endif
            }
#if SDR_USB_SEGMENT_PROFILE
            if(ok && s->bridge.released>release_before && usb_refill_active())
                usb_refill_event(USB_REFILL_ACK,sdr_usb_profile_clock(),0);
#endif
            s->usb.platform.leave(s->usb.platform.context,key);
            if (!ok) fault(s,5);
        }
    }
    if (s->phase==CP_USB_FAULT) {
        /* A USB failure does not itself stop the CP producer. Request STOP
         * when the mailbox cursor is still authoritative. An uncertain or
         * rejected command keeps its fault/pending owner; never overwrite it.
         */
        if (!s->cp_stopped && !s->stop_accepted && !s->mailbox->pending &&
            !s->mailbox->fault && s->mailbox->completed!=UINT32_MAX)
            (void)send(s,7u,0u,now);
        /* No proof of CP stop => no cancellation/close/reset of live storage.
         * Preserve unresolved CP commands for diagnostics/recovery.
         */
        if (s->cp_stopped && !s->cancelled) {
            iq_udc_cancel(&s->usb); s->cancelled=1;
        }
        if (s->cp_stopped && s->usb.opened) (void)iq_udc_close(&s->usb);
        return;
    }
    if (s->duration_ms && !s->stop_requested && (uint32_t)(now-s->started_ms)>=s->duration_ms)
        s->stop_requested=1;
    if (s->phase==CP_USB_RUNNING && (s->stop_requested || (snapshot->flags&1u))) {
        s->phase=CP_USB_STOPPING;
        s->stop_started_ms=now;
    }
    iq_udc_pump(&s->usb,s->ring.slots);
    if (s->usb.terminal_error) { fault(s,3); return; }
    if (s->phase==CP_USB_STOPPING && (uint32_t)(now-s->stop_started_ms)>=5000u) {
        fault(s,6); return;
    }
    if (s->mailbox->pending) return;
    if (s->stop_requested && !s->stop_accepted && !(snapshot->flags&1u)) {
        (void)send(s,7u,0u,now); return;
    }
    uint32_t key=s->usb.platform.enter(s->usb.platform.context);
    uint32_t release=cp_capture_release_begin(&s->bridge);
    uint32_t credit=cp_capture_claim_credit(&s->bridge);
    s->usb.platform.leave(s->usb.platform.context,key);
#if CP_USB_COMBINED_EXCHANGE
    if(release || (snapshot->published>s->bridge.claimed && credit)) {
        (void)send(s,14u,release?release:s->bridge.released,now);return;
    }
#else
    if (release) { (void)send(s,12u,release,now); return; }
    if (snapshot->published>s->bridge.claimed && credit) {
        (void)send(s,11u,s->bridge.claimed,now); return;
    }
#endif
    if (s->cp_stopped && snapshot->published==s->bridge.claimed &&
        s->bridge.claimed==s->bridge.released && snapshot->released==s->bridge.released &&
        iq_udc_close(&s->usb)) s->phase=CP_USB_DRAINED;
}
