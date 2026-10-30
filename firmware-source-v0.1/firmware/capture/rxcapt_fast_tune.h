#ifndef RXCAPT_FAST_TUNE_H
#define RXCAPT_FAST_TUNE_H
#if defined(RXCAPT_FAST_TUNE) && RXCAPT_FAST_TUNE
#define FAST_TRACE ((volatile uint32_t *)0x8096e000u)
static void clean_range(uint32_t,uint32_t);
/* Frame units, not CPU cycles or an assumed microsecond clock. */
static __attribute__((noinline,noclone)) uint32_t terminal_fast_clock(void) {
    for(unsigned i=0;i<8u;i++) {
        uint32_t before=R32(0x500900b8u)&1023u,packed=R32(0x500900bcu)&65535u;
        uint32_t after=R32(0x500900b8u)&1023u;
        if(before==after && (packed&15u)<10u)
            return before*10240u+(packed>>4)*10u+(packed&15u);
    }
    return 0xffffffffu;
}
static void terminal_fast_stage(uint32_t word) {
    if(word<8u || word>18u)return;
    FAST_TRACE[word]=terminal_fast_clock();FAST_TRACE[4]=M[36];
    FAST_TRACE[23]=M[37];
    clean_range((uint32_t)FAST_TRACE,128u);
}
static __attribute__((noinline,noclone)) uint32_t terminal_fast_init_required(void) {
    return M[32]==1u;
}
static void terminal_fast_begin(void) {
    uint32_t request=FAST_TRACE[8];
    for(unsigned i=0;i<32u;i++)FAST_TRACE[i]=0u;
    FAST_TRACE[0]=0x324e5446u;FAST_TRACE[1]=1u;FAST_TRACE[2]=M[32];
    FAST_TRACE[3]=CFG[9];FAST_TRACE[4]=M[36];FAST_TRACE[5]=1u;
    FAST_TRACE[7]=RXCAPT_FAST_TUNE_SETTLE_UNITS;
    FAST_TRACE[8]=M[32]==1u?terminal_fast_clock():request;
    FAST_TRACE[19]=!terminal_fast_init_required();FAST_TRACE[20]=R32(0x50006694u);
    terminal_fast_stage(9u);
}
static __attribute__((noinline,noclone)) uint32_t terminal_fast_wait_ready(void) {
    uint32_t wanted=CFG[9],old=FAST_TRACE[20],working=0u;
    unsigned ready=0u;
    for(unsigned i=0;i<1000000u;i++) {
        if(R32(0x50006698u))return 0x951u;
        working=R32(0x5000b53cu);
        if(R32(0x500066a8u)==wanted && R32(0x500066acu)==working &&
           R32(0x5000669cu)==1u && R32(0x50006694u)==working && working!=old) {
            ready=1u;break;
        }
    }
    if(!ready)return 0x952u;
    FAST_TRACE[21]=working;terminal_fast_stage(13u);
    uint32_t start=FAST_TRACE[13];
    if(start==0xffffffffu)return 0x953u;
    for(unsigned i=0;i<1000000u;i++) {
        uint32_t now=terminal_fast_clock();
        if(now==0xffffffffu)return 0x953u;
        uint32_t elapsed=(now+10485760u-start)%10485760u;
        if(elapsed>=RXCAPT_FAST_TUNE_SETTLE_UNITS) {FAST_TRACE[22]=elapsed;return 1u;}
    }
    return 0x954u;
}
#else
#define terminal_fast_begin() ((void)0)
#define terminal_fast_stage(word) ((void)0)
#endif
#endif
