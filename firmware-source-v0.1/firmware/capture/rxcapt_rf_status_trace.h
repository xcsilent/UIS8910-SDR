#ifndef RXCAPT_RF_STATUS_TRACE_H
#define RXCAPT_RF_STATUS_TRACE_H
/* Opt-in candidate only. Fixed-count phase observations, no polling, RF
 * writes, delays or IQ payload work. An MMIO bus stall has no software bound.
 * Legacy 8000-byte slots use dc00..de00; 8192-byte scratch slots end at
 * e000 and require the relocated e000..e200 record. Digital profile starts
 * at e200 and STREAM at e300. AP reads only after STOP/drain. */
#if defined(RXCAPT_RF_STATUS_TRACE) && RXCAPT_RF_STATUS_TRACE
#ifndef RF_STATUS_TRACE_ADDRESS
#define RF_STATUS_TRACE_ADDRESS 0x8096dc00u
#endif
#if RF_STATUS_TRACE_ADDRESS == 0x8096e000u
#if (defined(RXCAPT_FAST_TUNE) && RXCAPT_FAST_TUNE) || (defined(RXCAPT_STREAM_TIMING) && RXCAPT_STREAM_TIMING)
#error relocated_RF_trace_conflicts_with_timing_or_fast_tune
#endif
#endif
#if defined(RXCAPT_RF_STATUS_DUAL_BANK) && RXCAPT_RF_STATUS_DUAL_BANK
#if defined(RXCAPT_RF_STATUS_FEM_EXECUTION) && RXCAPT_RF_STATUS_FEM_EXECUTION
#define RF_STATUS_TRACE_ABI 5u
#elif defined(RXCAPT_RF_STATUS_FEM_COMMANDS) && RXCAPT_RF_STATUS_FEM_COMMANDS
#define RF_STATUS_TRACE_ABI 4u
#elif defined(RXCAPT_RF_STATUS_FEM) && RXCAPT_RF_STATUS_FEM
#define RF_STATUS_TRACE_ABI 3u
#else
#define RF_STATUS_TRACE_ABI 2u
#endif
#define RF_STATUS_TRACE_STRIDE 16u
#define RF_STATUS_TRACE_LIMIT 5u
#define RF_STATUS_TRACE_ROW_BYTES 64u
#else
#define RF_STATUS_TRACE_ABI 1u
#define RF_STATUS_TRACE_STRIDE 8u
#define RF_STATUS_TRACE_LIMIT 6u
#define RF_STATUS_TRACE_ROW_BYTES 32u
#endif
#if defined(RXCAPT_RF_STATUS_FEM_COMMANDS) && RXCAPT_RF_STATUS_FEM_COMMANDS
#include "rxcapt_fem_command_snapshot.h"
static uint32_t fem_trace_read32(void *context, uint32_t address) {
    (void)context;
    return R32(address);
}
#endif
static __attribute__((noinline,noclone)) void terminal_rf_status_trace(uint32_t stage) {
    volatile uint32_t *out=(volatile uint32_t *)RF_STATUS_TRACE_ADDRESS;
    if(!stage) {
        out[0]=0x52535431u;out[1]=RF_STATUS_TRACE_ABI;out[2]=TERM_GENERATION;out[3]=0;
#if defined(RXCAPT_RF_STATUS_FEM_EXECUTION) && RXCAPT_RF_STATUS_FEM_EXECUTION
        for(unsigned i=88u;i<128u;i++)out[i]=0;
        clean_range(RF_STATUS_TRACE_ADDRESS+88u*4u,160u);
#endif
#if defined(RXCAPT_RF_STATUS_FEM_COMMANDS) && RXCAPT_RF_STATUS_FEM_COMMANDS
        for(unsigned i=FEM_COMMAND_TAIL_WORD;i<128u;i++)out[i]=0;
        clean_range(RF_STATUS_TRACE_ADDRESS+FEM_COMMAND_TAIL_WORD*4u,160u);
#endif
        clean_range(RF_STATUS_TRACE_ADDRESS,32u);return;
    }
    uint32_t count=out[3];if(count>=RF_STATUS_TRACE_LIMIT)return;
    volatile uint32_t *row=out+8u+count*RF_STATUS_TRACE_STRIDE;
    row[0]=stage;
    row[1]=R16(0x5003037cu);
    row[2]=R16(0x50030374u)|((uint32_t)R16(0x50030364u)<<16);
    row[3]=R16(0x50030410u)|((uint32_t)R16(0x50032a00u)<<16);
    row[4]=R16(0x500302e0u)|((uint32_t)R16(0x500302c0u)<<16);
    row[5]=R16(0x5000b464u)|((uint32_t)R16(0x5000b526u)<<16);
    row[6]=R32(0x5000b53cu);row[7]=M[3];
#if defined(RXCAPT_RF_STATUS_DUAL_BANK) && RXCAPT_RF_STATUS_DUAL_BANK
    /* ABI2: fixed five checkpoints only. Read native-width halfwords;
       neither cal_ready nor BBPLL lock alone proves RF LO lock/reception.
       512B reservation at RF_STATUS_TRACE_ADDRESS stays outside DMA/STREAM. */
    row[8]=R16(0x5003036cu);
    row[9]=R16(0x5000b538u)|((uint32_t)R16(0x5000b534u)<<16);
    row[10]=R16(0x50030468u)|((uint32_t)R16(0x50030480u)<<16);
    row[11]=R16(0x5000b4e0u)|((uint32_t)R16(0x5000b52au)<<16);
    row[12]=R16(0x50030324u)|((uint32_t)R16(0x50030354u)<<16);
    row[13]=row[14]=row[15]=0;
#if defined(RXCAPT_RF_STATUS_FEM) && RXCAPT_RF_STATUS_FEM
    /* ABI3 uses the same 512B DDR allocation. Copy saved RF RAM only;
       never touch the RFFE peripheral, trigger a read or replay init.
       Flags describe pointer/consistency/target, NOT completion or ACK.
       Native init loses timeout information by saving zero on timeout. */
    if(R32(0x50007e18u)==0x96b0u) {
        uint32_t target=R16(0x500096e4u),man=R16(0x500096e6u);
        uint32_t product=R16(0x500096e8u),expected=R16(0x5000a7fau)&255u;
        uint32_t target2=R16(0x500096e4u),man2=R16(0x500096e6u);
        uint32_t product2=R16(0x500096e8u);
        uint32_t flags=1u;
        if(target==target2 && man==man2 && product==product2)flags|=2u;
        if(expected>0u && expected<=15u && target==expected)flags|=4u;
        row[13]=target|(man<<16);row[14]=product|(expected<<16);row[15]=flags;
    }
#endif
#endif
#if defined(RXCAPT_RF_STATUS_FEM_EXECUTION) && RXCAPT_RF_STATUS_FEM_EXECUTION
    /* Cold-loaded matching RF image only. Read a fixed instruction signature
       before the count/pointer data; no RFFE MMIO or command replay. A stable
       pair is only a checkpoint, not atomic live telemetry or ACK evidence. */
    volatile uint32_t *execution=out+88u+count*8u;
    for(unsigned i=0;i<8u;i++)execution[i]=0;
    execution[0]=stage;
    execution[1]=R32(0x500010e8u);
    if(execution[1]==0x0120506fu) {
        execution[2]=R32(0x50006118u);
        execution[3]=R32(0x5000611cu);
        execution[4]=R32(0x50006118u);
        execution[5]=R32(0x5000611cu);
        execution[6]=1u;
        if(execution[2]==execution[4] && execution[3]==execution[5])execution[6]|=2u;
    }
    clean_range((uint32_t)execution,32u);
#endif
#if defined(RXCAPT_RF_STATUS_FEM_COMMANDS) && RXCAPT_RF_STATUS_FEM_COMMANDS
    if(stage==2u || stage==3u) {
        uint32_t observation[FEM_COMMAND_ROW_WORDS];
        fem_command_observe(observation,stage,fem_trace_read32,0);
        volatile uint32_t *tail=out+FEM_COMMAND_TAIL_WORD+(stage-2u)*FEM_COMMAND_ROW_WORDS;
        for(unsigned i=0;i<FEM_COMMAND_ROW_WORDS;i++)tail[i]=observation[i];
        clean_range((uint32_t)tail,FEM_COMMAND_ROW_WORDS*4u);
    }
#endif
    clean_range((uint32_t)row,RF_STATUS_TRACE_ROW_BYTES);
    out[3]=count+1u;clean_range(RF_STATUS_TRACE_ADDRESS,32u);
}
#else
#define terminal_rf_status_trace(stage) ((void)0)
#endif
#endif
