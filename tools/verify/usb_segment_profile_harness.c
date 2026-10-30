#include "../../firmware/sdr_receiver/usb_segment_profile.h"
static uint64_t clock_us;
static unsigned clock_reads;
uint64_t sdr_usb_profile_clock(void){++clock_reads;clock_us+=10;return clock_us;}
#define main old_adapter_test_main
#include "iq_udc_adapter_harness.c"
#undef main
int main(void)
{
    assert(!usb_segment_profile_enabled());
    assert(!usb_segment_profile_configure(2));
    old_adapter_test_main();assert(!clock_reads); /* disabled => no clock calls */
    assert(usb_segment_profile_configure(1));usb_segment_profile_reset();
    setup(1);assert(iq_udc_open(&adapter,&ring,&fake.udc,&ep,platform()));
    fake.synchronous=1;publish();assert(iq_udc_pump(&adapter,1)==1);
    uint32_t w[40];usb_segment_profile_words(w);
    assert(w[6]==1 && w[16]==1 && w[26]==1 && w[7]==10 && w[17]==20 && w[27]==10);
    assert(!adapter.request[0].profiled && !adapter.request[0].pending && ring.stats.completed==1);
    assert(adapter.queue_observer.synchronous==1 && !adapter.queue_observer.accepted && !adapter.queue_observer.empty_completions);
    assert(iq_udc_close(&adapter));
    /* Two accepted requests: first completion retains supply, second empties it. */
    usb_segment_profile_reset();setup(2);assert(iq_udc_open(&adapter,&ring,&fake.udc,&ep,platform()));
    publish();publish();assert(iq_udc_pump(&adapter,2)==2 && adapter.queue_observer.accepted==2);
    complete(1,0,8192);assert(adapter.queue_observer.accepted==1 && adapter.queue_observer.completions==1 && !adapter.queue_observer.empty_completions);
    complete(0,0,8192);assert(!adapter.queue_observer.accepted && adapter.queue_observer.completions==2 && adapter.queue_observer.empty_completions==1);
    publish();assert(iq_udc_pump(&adapter,1)==1);
    assert(adapter.queue_observer.gap_count==1 && adapter.queue_observer.gap_total_us>0 && !adapter.queue_observer.gap_open);
    uint32_t refill_words[USB_REFILL_WORDS];usb_refill_words(refill_words);
    assert(refill_words[5]==1 && refill_words[6]==1 && !refill_words[7] && !refill_words[8]);
    assert(refill_words[10]==1 && refill_words[11]==16 && refill_words[16]>0);
    complete(2,0,8192);
    assert(iq_udc_close(&adapter));
    /* Fail before enqueue: prepare counted, no queue call/completion. */
    usb_segment_profile_reset();setup(1);assert(iq_udc_open(&adapter,&ring,&fake.udc,&ep,platform()));
    fake.fail_prepare=1;publish();iq_udc_pump(&adapter,1);usb_segment_profile_words(w);
    assert(w[6]==1 && !w[16] && !w[26] && !adapter.request[0].profiled);
    assert(iq_udc_close(&adapter));
    /* Rejected enqueue has call timing but no invented completion. */
    usb_segment_profile_reset();setup(1);assert(iq_udc_open(&adapter,&ring,&fake.udc,&ep,platform()));
    fake.reject=1;publish();iq_udc_pump(&adapter,1);usb_segment_profile_words(w);
    assert(w[6]==1 && w[16]==1 && !w[26] && !adapter.request[0].profiled);
    assert(adapter.queue_observer.rejected==1 && !adapter.queue_observer.accepted);assert(iq_udc_close(&adapter));
    /* Deferred cancellation records real callback, not cancel request time. */
    usb_segment_profile_reset();setup(1);assert(iq_udc_open(&adapter,&ring,&fake.udc,&ep,platform()));
    publish();assert(iq_udc_pump(&adapter,1)==1);iq_udc_cancel(&adapter);
    usb_segment_profile_words(w);assert(!w[26]);clock_us+=500;complete(0,-125,0);
    usb_segment_profile_words(w);assert(w[26]==1 && w[27]>=500 && w[35]==1);
    assert(adapter.queue_observer.cancelled==1 && !adapter.queue_observer.empty_completions && !adapter.queue_observer.accepted);assert(iq_udc_close(&adapter));
    usb_segment_profile_exchange(2,3);usb_segment_profile_words(w);assert(w[3]==1 && w[4]==2 && w[5]==3);
    usb_segment_profile_reset();usb_segment_profile_words(w);assert(w[2]==1 && !w[3] && !w[6]);
    /* Bounded chronological retention, zero-offset observations, repeats,
     * observations predating an episode, aborts and 64-bit clock crossing. */
    for(unsigned i=0;i<30;++i) {
        uint64_t start=UINT32_MAX+(uint64_t)i*1000;
        usb_refill_begin(start);
        usb_refill_event(USB_REFILL_WORKER,start,0xe01);
        usb_refill_event(USB_REFILL_WORKER,start+5,0); /* first wins */
        usb_refill_event(USB_REFILL_RELEASE,start+10,0);
        usb_refill_event(USB_REFILL_ACK,start+30,0);
        usb_refill_event(USB_REFILL_PUBLISHED,start+40,0);
        usb_refill_end(1,start+50);
    }
    usb_refill_words(refill_words);
    assert(refill_words[5]==30 && refill_words[6]==30 && refill_words[9]==24);
    for(unsigned i=0;i<24;++i) {
        uint32_t *r=refill_words+10+8*i;
        assert(r[0]==i+7 && r[1]==31 && !r[2] && r[3]==10 && r[4]==30 && r[5]==40 && r[6]==50 && r[7]==0xe01);
    }
    usb_refill_begin(100);usb_refill_end(0,110);
    usb_refill_begin(200);usb_refill_event(USB_REFILL_PUBLISHED,220,0);
    usb_refill_end(1,250);usb_refill_words(refill_words);
    assert(refill_words[5]==32 && refill_words[6]==31 && refill_words[7]==1);
    uint32_t *last=refill_words+10+8*23;
    assert(last[0]==32 && last[1]==24 && !last[2] && last[5]==20 && last[6]==50);
    usb_segment_profile_reset();usb_refill_words(refill_words);
    assert(!refill_words[5] && !refill_words[9] && !usb_refill_active());
    usb_segment_profile_configure(0);unsigned before=clock_reads;old_adapter_test_main();assert(clock_reads==before);
    puts("segment profiling passed: disabled clock avoidance, sync/deferred completion, prepare failure, rejected enqueue, cancel and session reset; payload untouched");
    return 0;
}
