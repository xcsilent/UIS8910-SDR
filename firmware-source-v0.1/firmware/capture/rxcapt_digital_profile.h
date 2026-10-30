#ifndef UIS8910_RXCAPT_DIGITAL_PROFILE_H
#define UIS8910_RXCAPT_DIGITAL_PROFILE_H
/* Optional digital-only diagnostic, outside DATA and all service metadata.
 * Three records: after PREPARE, after RF request, before RF/DMA shutdown. */
#if defined(RXCAPT_DIGITAL_PROFILE_TRACE) && RXCAPT_DIGITAL_PROFILE_TRACE
static __attribute__((noinline)) void terminal_digital_profile(uint32_t phase) {
    volatile uint32_t *out=(volatile uint32_t *)0x8096e200u;
    if(phase<1u || phase>3u)return;
    if(phase==1u) {
        for(unsigned i=0;i<16;i++)out[i]=0;
        out[0]=0x44505231u;out[1]=1u;out[2]=TERM_GENERATION;
    }
    out[3]=1u;
    unsigned row=4u+(phase-1u)*4u;
    out[row]=phase;out[row+1u]=R32(0x25000038u);
    out[row+2u]=R32(0x25000020u);out[row+3u]=CFG[4];
    __asm__ volatile("dmb sy":::"memory");
    out[3]=phase==3u?2u:1u;
    clean_range(0x8096e200u,64u);
}
#else
#define terminal_digital_profile(phase) ((void)0)
#endif
#endif
