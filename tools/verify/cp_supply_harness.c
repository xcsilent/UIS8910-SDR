/* Current/legacy geometry, real AP bridge/mailbox and CP batch core.
 * Synthetic event order only: no peripheral time or throughput prediction. */
#define main legacy_stream_test_main
#include "cp_usb_stream_harness.c"
#undef main

int main(void)
{
    for(unsigned refill_after_ack=0;refill_after_ack<2;++refill_after_ack) {
        setup();open_stream();produce(TEST_SLOTS);
        tick();cp_poll();tick();
        assert(queued_count==TEST_SLOTS);
        for(unsigned round=0;round<8;++round) {
            uint32_t end=cp[6];
            for(unsigned i=0;i<TEST_SLOTS;++i)finish(i,0,TEST_BYTES);
            queued_count=0;
            tick();assert(mailbox.pending && mailbox.operation==14 && mailbox.block==end);
            /* USB done is not CP release. Delay the ACK: no reuse or submit. */
            assert(cp[7]==end-TEST_SLOTS);
            for(unsigned i=0;i<3;++i)tick();
            assert(cp[7]==end-TEST_SLOTS && !queued_count);
            cp_poll();assert(cp[7]==end);
            if(!refill_after_ack)produce(TEST_SLOTS);
            tick();assert(stream.bridge.released==end && !queued_count);
            if(refill_after_ack) {
                assert(!mailbox.pending);
                produce(TEST_SLOTS);tick();
            }
            assert(mailbox.pending && mailbox.operation==14 && mailbox.block==end);
            cp_poll();tick();assert(queued_count==TEST_SLOTS);
            assert(stream.bridge.claimed==end+TEST_SLOTS && !stream.usb.terminal_error);
        }
        cp_usb_stream_stop(&stream);tick();cp_poll();phase=30;tick();
        for(unsigned i=0;i<TEST_SLOTS;++i)finish(i,0,TEST_BYTES);
        tick();cp_poll();tick();
        assert(stream.phase==CP_USB_DRAINED && allocated==freed);
        assert(cp[6]==cp[7] && cp[7]==9u*TEST_SLOTS);
        assert(stream.ring.stats.completed_bytes==9u*TEST_SLOTS*TEST_BYTES);
    }
    printf("supply event orders passed: slots=%u bytes=%u, 8 wraps/order, delayed release ACK pins CP ownership; post-release refill needs another claim exchange; stopped/drained\n",TEST_SLOTS,TEST_BYTES);
    return 0;
}
