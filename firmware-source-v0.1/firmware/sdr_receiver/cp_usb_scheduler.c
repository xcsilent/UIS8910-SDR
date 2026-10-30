#include "cp_usb_scheduler.h"

static unsigned bucket(uint64_t us)
{
    const uint32_t edges[5]={50,100,250,500,1000};
    for(unsigned i=0;i<5;++i)if(us<=edges[i])return i;
    return 5;
}
static uint32_t clipped(uint64_t v) { return v>UINT32_MAX?UINT32_MAX:(uint32_t)v; }
int cp_usb_scheduler_configure(struct cp_usb_scheduler *s,uint32_t wait,uint32_t burst)
{
    if(!s || wait<25u || wait>1000u || burst>50u)return 0;
    s->wait_us=wait;s->burst_us=burst;s->burst_polls=0;s->manual_override=1;return 1;
}
void cp_usb_scheduler_automatic(struct cp_usb_scheduler *s)
{
    s->manual_override=0;s->burst_us=0;s->burst_polls=0;
    s->wait_us=s->bandwidth_index>=CP_USB_SCHEDULER_WIDE_MIN_BW?100u:250u;
}
int cp_usb_scheduler_begin(struct cp_usb_scheduler *s,uint32_t bandwidth)
{
    if(!s || bandwidth>5u)return 0;
    s->bandwidth_index=bandwidth;
    if(!s->manual_override)cp_usb_scheduler_automatic(s);
    cp_usb_scheduler_reset(s);return 1;
}
void cp_usb_scheduler_reset(struct cp_usb_scheduler *s)
{
    uint32_t wait=s->wait_us?s->wait_us:250u,burst=s->burst_us;
    uint32_t manual=s->manual_override,bandwidth=s->bandwidth_index;
    *s=(struct cp_usb_scheduler){0};s->wait_us=wait;s->burst_us=burst;
    s->manual_override=manual;s->bandwidth_index=bandwidth;
}
void cp_usb_scheduler_observe(struct cp_usb_scheduler *s,uint32_t pending,uint32_t completed,uint64_t now)
{
    ++s->ticks;
    if(s->pending && completed==s->pending) {
        uint64_t latency=now-s->queued_at;
        ++s->acks;s->ack_us+=latency;++s->ack_hist[bucket(latency)];
        if(latency>s->max_ack_us)s->max_ack_us=clipped(latency);
        s->pending=0;
    }
    if(pending && pending!=s->pending) {s->pending=pending;s->queued_at=now;}
}
uint32_t cp_usb_scheduler_wait(struct cp_usb_scheduler *s,uint32_t notified,uint32_t may_wait,uint32_t pending,uint64_t now)
{
    ++s->waits;
    if(notified) {++s->notifications;s->burst_polls=0;return 0;}
    if(!may_wait)return 0;
    if(pending && s->burst_us) {
        if(!s->burst_polls)s->burst_at=now;
        if(s->burst_polls<CP_USB_SCHEDULER_MAX_POLLS && now-s->burst_at<s->burst_us) {
            ++s->burst_polls;++s->fast_polls;return 0;
        }
        ++s->exhaustions;
    }
    s->burst_polls=0;++s->sleeps;
    return s->wait_us?s->wait_us:250u;
}
void cp_usb_scheduler_slept(struct cp_usb_scheduler *s,uint64_t us)
{
    s->sleep_us+=us;++s->sleep_hist[bucket(us)];
    if(us>s->max_sleep_us)s->max_sleep_us=clipped(us);
}
void cp_usb_scheduler_words(const struct cp_usb_scheduler *s,uint32_t out[CP_USB_SCHEDULER_WORDS])
{
    out[0]=0x31484353u;out[1]=1;out[2]=s->wait_us?s->wait_us:250u;out[3]=s->burst_us;
    out[4]=s->waits;out[5]=s->notifications;out[6]=s->sleeps;out[7]=s->fast_polls;
    out[8]=s->exhaustions;out[9]=s->ticks;out[10]=(uint32_t)s->sleep_us;out[11]=(uint32_t)(s->sleep_us>>32);
    out[12]=s->max_sleep_us;out[13]=s->acks;out[14]=(uint32_t)s->ack_us;out[15]=(uint32_t)(s->ack_us>>32);out[16]=s->max_ack_us;
    for(unsigned i=0;i<6;++i){out[17+i]=s->sleep_hist[i];out[23+i]=s->ack_hist[i];}
    out[29]=CP_USB_SCHEDULER_MAX_POLLS;
}
