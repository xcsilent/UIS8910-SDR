#include <assert.h>
#include <stdio.h>
#include "../../firmware/rf_rebuild/rfad_raw_capture.h"
#include "../../firmware/sdr_receiver/sample_rate.h"
static unsigned writes;
static uint32_t precfg;
/* DMA is outside this geometry-only test and must never be invoked. */
enum rfad_raw_dma_result rfad_raw_dma_copy_bounded(const struct rf_bus *b,
    uint32_t t,uint32_t s,uint32_t d,uint32_t n,uint32_t p,uint32_t q)
{
    (void)b;(void)t;(void)s;(void)d;(void)n;(void)p;(void)q;
    assert(0);return RFAD_RAW_DMA_BAD_ARGUMENT;
}
static void write_reg(void *ctx,uint32_t address,uint32_t value,unsigned width)
{
    (void)ctx;assert(width==4);++writes;
    if(address==0x25000038u) precfg=value;
}
int main(void)
{
    struct rf_bus bus={0,0,write_reg};
    for(unsigned bw=0;bw<6;++bw) {
        struct rfad_raw_rx_geometry g;
        writes=0;assert(!rfad_raw_rx_prepare_capture(&bus,bw,&g));
        assert(sdr_nominal_sample_rate(bw)==g.cycle_words*1000u);
        assert(writes==5 && precfg==((bw<<8)|8));
        struct rfad_raw_rx_capture capture;
        assert(rfad_raw_rx_capture_begin(&capture,0x80900000,g.cycle_words*4-1,&g)==-1);
        assert(!rfad_raw_rx_capture_begin(&capture,0x80900000,g.cycle_words*4,&g));
        uint32_t total=0;
        for(unsigned i=0;i<14;++i) {
            struct rfad_raw_rx_block block;
            assert(rfad_raw_rx_capture_next(&capture,&block)==RFAD_RAW_RX_CAPTURE_BLOCK_READY);
            assert(block.destination==0x80900000+total);
            total+=block.bytes;
            int result=rfad_raw_rx_capture_commit(&capture,&block,1);
            assert(result==(i==13?RFAD_RAW_RX_CAPTURE_HELD_RESULT:RFAD_RAW_RX_CAPTURE_CONTINUE));
        }
        assert(total==g.cycle_words*4);
        printf("%u %u %u %u %u\n",bw,g.cycle_words,g.first_block_words,g.other_block_words,precfg);
    }
    struct rfad_raw_rx_geometry g;writes=0;
    assert(rfad_raw_rx_prepare_capture(&bus,6,&g)==-1 && !writes);
    assert(!sdr_nominal_sample_rate(6) && !sdr_nominal_sample_rate(UINT32_MAX));
    return 0;
}
