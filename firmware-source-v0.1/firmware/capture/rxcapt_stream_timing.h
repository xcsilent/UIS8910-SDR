#ifndef UIS8910_RXCAPT_STREAM_TIMING_H
#define UIS8910_RXCAPT_STREAM_TIMING_H

/* Optional finite diagnostic: first seven paired DMA completions. The 288 B
 * trace lies after the seven DATA slots and before the existing state export.
 * It measures observed completion spacing, not the ADC/sample clock. */
#if defined(RXCAPT_STREAM_TIMING) && RXCAPT_STREAM_TIMING
#define STREAM_TIMING_ADDRESS 0x8096e000u
#define STREAM_TIMING_WORDS 72u
#define STREAM_TIMING_ROWS 16u
#define TIMING ((volatile uint32_t *)STREAM_TIMING_ADDRESS)

static void terminal_stream_timing_begin(void) __attribute__((noinline));
static void terminal_stream_timing_record(const struct rf_bus *,uint32_t,uint32_t)
    __attribute__((noinline));
static void terminal_stream_timing_finish(void) __attribute__((noinline));

static void terminal_stream_timing_begin(void) {
    for(unsigned i=0;i<STREAM_TIMING_WORDS;i++)TIMING[i]=0;
    TIMING[0]=0x54494d32u;TIMING[1]=1u;TIMING[2]=TERM_GENERATION;
    TIMING[3]=STREAM_TIMING_ROWS;TIMING[5]=R32(0x500900c4u)&65535u;
    TIMING[7]=1u;
}
static void terminal_stream_timing_record(const struct rf_bus *bus,uint32_t kind,uint32_t sequence) {
    if((kind==1u || kind==2u) && sequence>=7u)return;
    uint32_t index=TIMING[4];
    if(index>=STREAM_TIMING_ROWS)return;
    struct rfad_frame_time now;
    enum rfad_frame_time_result result=rfad_read_frame_time_bounded(bus,0u,64u,&now);
    uint32_t row=8u+index*4u;
    TIMING[row]=kind|(sequence<<8);
    if(result==RFAD_FRAME_TIME_OK) {
        TIMING[row+1u]=now.cycle;TIMING[row+2u]=now.ssfn;TIMING[row+3u]=now.offset;
    } else {
        TIMING[row+1u]=0xffffffffu;TIMING[row+2u]=(uint32_t)result;TIMING[row+3u]=0;
        TIMING[6]++;
    }
    TIMING[4]=index+1u;
}
static void terminal_stream_timing_finish(void) {
    __asm__ volatile("dmb sy":::"memory");
    TIMING[7]=2u;
    clean_range(STREAM_TIMING_ADDRESS,STREAM_TIMING_WORDS*4u);
}
#else
#define terminal_stream_timing_begin() ((void)0)
#define terminal_stream_timing_record(bus,kind,sequence) ((void)0)
#define terminal_stream_timing_finish() ((void)0)
#endif
#endif
