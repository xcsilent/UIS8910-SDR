#define main legacy_stream_test_main
#include "cp_usb_stream_harness.c"
#undef main
#if SDR_USB_SEGMENT_PROFILE
#include "../../firmware/sdr_receiver/usb_segment_profile.h"
static uint64_t profile_clock;
uint64_t sdr_usb_profile_clock(void){profile_clock+=10;return profile_clock;}
#endif
int main(void)
{
#if SDR_USB_SEGMENT_PROFILE
    assert(usb_segment_profile_configure(1));usb_segment_profile_reset();
#endif
    setup();open_stream();produce(3);
    tick();assert(mailbox.pending && mailbox.operation==14 && mailbox.block==0 && !queued_count);
    tick();assert(!queued_count && !stream.bridge.claimed);
    cp_poll();tick();assert(queued_count==3 && stream.bridge.claimed==3 && cp[7]==0);
    finish(0,0,TEST_BYTES);produce(2);tick();
    assert(mailbox.pending && mailbox.operation==14 && mailbox.block==1 && cp[7]==0);
    tick();assert(stream.bridge.released==0 && queued_count==3); /* pending preserves ownership */
    cp_poll();tick();assert(cp[7]==1 && stream.bridge.released==1 && stream.bridge.claimed==5 && queued_count==5);
    cp_usb_stream_stop(&stream);tick();assert(mailbox.operation==7 && mailbox.pending);
    cp_poll();phase=30;tick();
    for(unsigned i=1;i<5;++i)finish(i,0,TEST_BYTES);
    tick();assert(mailbox.operation==14 && mailbox.block==5);cp_poll();tick();
    assert(stream.phase==CP_USB_DRAINED && freed==allocated && cp[7]==5);
#if SDR_USB_SEGMENT_PROFILE
    uint32_t profile_words[40];usb_segment_profile_words(profile_words);
    assert(profile_words[4]==5 && profile_words[5]==5 && profile_words[3]==3);
    assert(profile_words[6]==5 && profile_words[16]==5 && profile_words[26]==5);
#endif

    /* Real worker event order across a full drain, release ACK, later
     * publication, claim ACK and UDC refill. No CP reuse before release. */
#if SDR_USB_SEGMENT_PROFILE
    usb_segment_profile_reset();setup();open_stream();produce(2);
    tick();cp_poll();tick();finish(0,0,TEST_BYTES);finish(1,0,TEST_BYTES);
    assert(usb_refill_active());tick();assert(mailbox.pending && cp[7]==0);
    cp_poll();tick();assert(cp[7]==2 && !stream.usb.queue_observer.accepted);
    produce(2);tick();assert(mailbox.pending);cp_poll();tick();
    uint32_t refill[USB_REFILL_WORDS];usb_refill_words(refill);
    assert(refill[5]==1 && refill[6]==1 && !refill[8] && refill[11]==31);
    assert(refill[12]<=refill[13] && refill[13]<=refill[14] &&
        refill[14]<=refill[15] && refill[15]<=refill[16]);
    cp_usb_stream_stop(&stream);tick();cp_poll();phase=30;tick();
    finish(2,0,TEST_BYTES);finish(3,0,TEST_BYTES);tick();cp_poll();tick();
    assert(stream.phase==CP_USB_DRAINED && freed==allocated);
#endif

    /* STOP arrives while exchange ACK is delayed: do not replace mailbox. */
    setup();open_stream();produce(2);tick();uint32_t pending=mailbox.pending;
    cp_usb_stream_stop(&stream);tick();assert(mailbox.pending==pending && mailbox.operation==14 && !queued_count);
    cp_poll();tick();assert(queued_count==2 && mailbox.operation==7);
    cp_poll();phase=30;tick();finish(0,0,TEST_BYTES);finish(1,0,TEST_BYTES);
    tick();cp_poll();tick();assert(stream.phase==CP_USB_DRAINED && freed==allocated);

    /* Valid frame with impossible claim end: AP commit fails atomically. */
    setup();open_stream();produce(1);tick();
    uint32_t reply[8]={0x52585331,GEN,1,14,0,0,8,1};memcpy(lines+8,reply,sizeof(reply));
    tick();assert(stream.phase==CP_USB_FAULT && stream.bridge.claimed==0 && stream.bridge.released==0 && !queued_count);

    /* USB fault after a valid exchange must stop CP before cancellation. */
    setup();open_stream();produce(2);tick();cp_poll();tick();
    finish(0,-1,TEST_BYTES);tick();assert(stream.phase==CP_USB_FAULT && !cancels && !freed);
    tick();assert(mailbox.pending && mailbox.operation==7);cp_poll();phase=30;tick();
    assert(cancels==1 && !freed);finish(1,-1,0);tick();assert(freed==allocated);
    puts("combined stream passed: one-round-trip release+claim, delayed ACK ownership, STOP ordering, malformed reply atomicity, USB-fault stop/cancel/drain");
    return 0;
}
