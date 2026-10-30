#ifndef RXCAPT_RF_TIMER_PROBE_H
#define RXCAPT_RF_TIMER_PROBE_H
#if defined(RXCAPT_RF_TIMER_PROBE) && RXCAPT_RF_TIMER_PROBE
#define RF_TIMER_PROBE ((volatile uint32_t *)0x8096e640u)
#define RF_TIMER_PROBE_CONTROL 0x50038000u
#define RF_TIMER_PROBE_COUNT 0x50038004u
#define RF_TIMER_PROBE_COMPARE 0x50038008u
#define RF_TIMER_PROBE_STATUS 0x5003800cu
#define RF_TIMER_PROBE_REFERENCE 0x50090088u
#define RF_TIMER_PROBE_POLL_LIMIT 1000000u

/* Called only after the receiver and both DMA channels have stopped. */
static __attribute__((noinline,noclone)) void terminal_rf_timer_probe(void) {
    volatile uint32_t *out=RF_TIMER_PROBE;
    for(unsigned i=0;i<32u;i++)out[i]=0;
    out[0]=0x31425054u; /* TPB1 */
    out[1]=1u;out[2]=TERM_GENERATION;out[3]=1u;
    out[4]=R32(RF_TIMER_PROBE_CONTROL);
    out[5]=R32(RF_TIMER_PROBE_COUNT);
    out[6]=R32(RF_TIMER_PROBE_COMPARE);
    out[7]=R32(RF_TIMER_PROBE_STATUS);
    out[8]=R32(RF_TIMER_PROBE_REFERENCE);
    clean_range(0x8096e640u,128u);
    if((out[4]&11u) || (out[7]&1u) || out[6]!=122u) {
        out[21]=3u;out[3]=5u;clean_range(0x8096e640u,128u);return;
    }

    R32(RF_TIMER_PROBE_CONTROL)=out[4]&0xfffffff4u;
    R32(RF_TIMER_PROBE_COUNT)=0u;
    R32(RF_TIMER_PROBE_COMPARE)=122u;
    R32(RF_TIMER_PROBE_STATUS)=1u;
    out[9]=R32(RF_TIMER_PROBE_STATUS);
    if(out[9]&1u) {
        R32(RF_TIMER_PROBE_CONTROL)=R32(RF_TIMER_PROBE_CONTROL)&0xfffffff4u;
        out[16]=R32(RF_TIMER_PROBE_CONTROL);out[17]=R32(RF_TIMER_PROBE_COUNT);
        out[18]=R32(RF_TIMER_PROBE_COMPARE);out[19]=R32(RF_TIMER_PROBE_STATUS);
        out[20]=R32(RF_TIMER_PROBE_REFERENCE);out[21]=4u;
        out[22]=out[20]-out[8];out[3]=5u;clean_range(0x8096e640u,128u);return;
    }

    out[3]=2u;clean_range(0x8096e640u,128u);
    R32(RF_TIMER_PROBE_CONTROL)=11u;
    out[10]=R32(RF_TIMER_PROBE_CONTROL);out[11]=R32(RF_TIMER_PROBE_COUNT);
    uint32_t status=0u,reads=0u;
    if(out[10]==11u) {
        for(reads=1u;reads<=RF_TIMER_PROBE_POLL_LIMIT;reads++) {
            status=R32(RF_TIMER_PROBE_STATUS);
            if(status&1u)break;
        }
    }
    out[12]=reads>RF_TIMER_PROBE_POLL_LIMIT?RF_TIMER_PROBE_POLL_LIMIT:reads;
    out[13]=status;out[14]=R32(RF_TIMER_PROBE_COUNT);
    if(status&1u)R32(RF_TIMER_PROBE_STATUS)=1u;
    R32(RF_TIMER_PROBE_CONTROL)=R32(RF_TIMER_PROBE_CONTROL)&0xfffffff4u;
    out[15]=R32(RF_TIMER_PROBE_STATUS);
    out[16]=R32(RF_TIMER_PROBE_CONTROL);out[17]=R32(RF_TIMER_PROBE_COUNT);
    out[18]=R32(RF_TIMER_PROBE_COMPARE);out[19]=R32(RF_TIMER_PROBE_STATUS);
    out[20]=R32(RF_TIMER_PROBE_REFERENCE);
    out[21]=out[10]==11u?((status&1u)?1u:2u):4u;
    out[22]=out[20]-out[8];out[3]=(out[21]==1u)?3u:4u;
    clean_range(0x8096e640u,128u);
}
#endif
#endif
