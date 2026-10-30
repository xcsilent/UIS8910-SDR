/* AP owns request cache line; CP owns response cache line. Never share a
 * writable line between CPUs. This service never resumes modem tasks. */
#include <stdint.h>
#include "terminal_binding.h"
#include "rxcapt_profile.h"

extern void terminal_hold(void) __attribute__((noreturn));
#define SERVICE_MAGIC 0x52585331u
#define Q ((volatile uint32_t *)TERM_SERVICE_MAILBOX)
#define A ((volatile uint32_t *)(TERM_SERVICE_MAILBOX+32u))
#define CFG ((volatile uint32_t *)TERM_CONFIG)

#if defined(RXCAPT_CONTINUOUS_STREAM) && RXCAPT_CONTINUOUS_STREAM
#ifndef RXCAPT_STREAM_STATE_ADDRESS
#error continuous stream service requires an explicit AP-readable state address
#endif
#define STREAM ((volatile uint32_t *)RXCAPT_STREAM_STATE_ADDRESS)
extern uint32_t rxcapt_stream_claim(volatile uint32_t *,uint32_t);
extern uint32_t rxcapt_stream_release(volatile uint32_t *,uint32_t);
extern uint32_t rxcapt_stream_request_stop(volatile uint32_t *);
extern uint32_t rxcapt_stream_dma_idle(volatile uint32_t *);
#if defined(RXCAPT_USB_BATCH) && RXCAPT_USB_BATCH
#include "rxcapt_stream_batch.h"
#ifndef RXCAPT_USB_MAX_BW
#define RXCAPT_USB_MAX_BW 0u
#endif
#endif
#endif

/* Packed user parameters: channel[15:0], bandwidth index[18:16],
 * gain index[25:19]. Upper six bits must be zero. This first runtime
 * interface stays on the reviewed TDD B40 path; these are not chip limits. */
static int apply_parameters(uint32_t packed) {
    uint32_t channel=packed&65535u,bw=(packed>>16)&7u,gain=(packed>>19)&127u;
    if((packed>>26) || channel<2400u || channel>2649u || !bw || bw>5u ||
       gain>124u || CFG[1]!=2u || CFG[2]!=1u)return 0;
    CFG[3]=channel;CFG[4]=bw;CFG[5]=gain;CFG[9]=0;
    return 1;
}

/* First raw-frequency experiment keeps the established profile and permits
 * +/-1000 raw units around its anchor. This is an experiment envelope, not
 * a PLL range or resolution claim. Zero denotes ordinary channel mode. */
static int apply_raw_frequency(uint32_t raw) {
    uint32_t anchor=8690000u+(CFG[3]-2400u)*1000u;
    if(CFG[1]!=2u || CFG[2]!=1u || CFG[3]<2400u || CFG[3]>2649u ||
       raw<8690000u || raw>8939000u ||
       (raw>anchor?raw-anchor:anchor-raw)>1000u)return 0;
    CFG[9]=raw;return 1;
}

static void invalidate_request(void) {
    uint32_t line=TERM_SERVICE_MAILBOX;
    __asm__ volatile("dsb sy\nmcr p15,0,%0,c7,c6,1\ndsb sy"::"r"(line):"memory");
}
static void response(uint32_t sequence,uint32_t phase,uint32_t error) {
    /* The verified CP section descriptor 0x80f089e2 has AP=6 (read-only),
       domain 15. Scope the existing manager-domain technique to this one
       response cache line, then restore the exact incoming DACR. */
    uint32_t saved,manager;
    __asm__ volatile("mrc p15,0,%0,c3,c0,0":"=r"(saved));
    manager=saved|(3u<<30);
    __asm__ volatile("dsb sy\nmcr p15,0,%0,c3,c0,0\nisb sy"::"r"(manager):"memory");
    A[0]=SERVICE_MAGIC;A[1]=TERM_GENERATION;A[2]=sequence;
    A[3]=phase;A[4]=error;A[5]=0;A[6]=0;A[7]=sequence;
    uint32_t line=TERM_SERVICE_MAILBOX+32u;
    __asm__ volatile("dmb sy\nmcr p15,0,%0,c7,c10,1\ndsb sy"::"r"(line):"memory");
    __asm__ volatile("mcr p15,0,%0,c3,c0,0\nisb sy"::"r"(saved):"memory");
}

#if defined(RXCAPT_CONTINUOUS_STREAM) && RXCAPT_CONTINUOUS_STREAM
static void stream_response(uint32_t sequence,uint32_t phase,uint32_t error,
                            uint32_t value0,uint32_t value1) {
    uint32_t saved,manager;
    __asm__ volatile("mrc p15,0,%0,c3,c0,0":"=r"(saved));
    manager=saved|(3u<<30);
    __asm__ volatile("dsb sy\nmcr p15,0,%0,c3,c0,0\nisb sy"::"r"(manager):"memory");
    A[0]=SERVICE_MAGIC;A[1]=TERM_GENERATION;A[2]=sequence;
    A[3]=phase;A[4]=error;A[5]=value0;A[6]=value1;A[7]=sequence;
    uint32_t line=TERM_SERVICE_MAILBOX+32u;
    __asm__ volatile("dmb sy\nmcr p15,0,%0,c7,c10,1\ndsb sy"::"r"(line):"memory");
    __asm__ volatile("mcr p15,0,%0,c3,c0,0\nisb sy"::"r"(saved):"memory");
}

static void stream_clean_state(void) {
#ifdef RXCAPT_STREAM_EXPORT_ADDRESS
    extern void terminal_stream_publish(void);
    terminal_stream_publish();
#else
    uint32_t address=(uint32_t)STREAM;
    for(uint32_t line=address&~31u;line<address+30u*4u;line+=32u)
        __asm__ volatile("mcr p15,0,%0,c7,c10,1"::"r"(line):"memory");
    __asm__ volatile("dsb sy":::"memory");
#endif
}

/* AP command sequence is independent of DATA/HEAD block sequence. CLAIM and
 * RELEASE carry the block sequence in request[5]; STOP is accepted while the
 * DMA poller continues to own CP, and PARK is legal only after the queue drains. */
void terminal_stream_poll(void) {
    if(!TERM_SERVICE_MAILBOX)return;
    volatile uint32_t *last=(volatile uint32_t *)(TERM_META+31u*4u);
    uint32_t request[8];
    invalidate_request();
    for(unsigned i=0;i<8;i++)request[i]=Q[i];
    invalidate_request();
    unsigned stable=0;
    for(unsigned i=0;i<8;i++)if(request[i]!=Q[i])break;else ++stable;
    if(stable!=8 || request[0]!=SERVICE_MAGIC ||
       request[1]!=TERM_GENERATION || request[6]!=~request[2] ||
       request[7]!=request[2] || request[2]==*last)return;
    if(request[2]!=*last+1u || request[4]!=*last) {
        stream_response(request[2],4u,0xc10u,0u,0u);return;
    }
    uint32_t op=request[3],block=request[5],result=0u;
#if defined(RXCAPT_USB_BATCH) && RXCAPT_USB_BATCH
    if(op==13u) {
        uint32_t channel=block&65535u,gain=(block>>19)&127u,bw=(block>>16)&7u;
#if defined(RXCAPT_EXPERIMENTAL_PRE_SWITCH) && RXCAPT_EXPERIMENTAL_PRE_SWITCH
        uint32_t selector=(block>>26)&7u;
        uint32_t invalid_extension=(block>>29) || (selector && (selector<5u || bw!=5u));
#elif defined(RXCAPT_EXPERIMENTAL_FEM_OVERRIDE) && RXCAPT_EXPERIMENTAL_FEM_OVERRIDE
        uint32_t fem=(block>>26)&3u;
        uint32_t fem_channel=(channel>=2400u && channel<=2649u) ||
                             (channel>=3450u && channel<=3799u);
        uint32_t invalid_extension=(block>>28) || fem==3u || (fem && !fem_channel) ||
            *(volatile uint32_t *)(TERM_META+43u*4u);
#else
        uint32_t invalid_extension=block>>26;
#endif
        uint32_t phase=*(volatile uint32_t *)(TERM_META+12u);
        if(phase!=30u || !(STREAM[3]&1u) || STREAM[7]!=STREAM[6] ||
           !rxcapt_stream_dma_idle(STREAM) || (STREAM[8]!=1u && STREAM[8]!=2u) ||
           invalid_extension || bw>RXCAPT_USB_MAX_BW || !terminal_profile_channel_valid(channel) || gain>124u ||
           CFG[1]!=2u || CFG[2]!=1u) {
            stream_response(request[2],4u,0xc17u,block,op);return;
        }
        CFG[3]=channel;CFG[4]=bw;CFG[5]=gain;CFG[9]=0u;
#if defined(RXCAPT_EXPERIMENTAL_FEM_OVERRIDE) && RXCAPT_EXPERIMENTAL_FEM_OVERRIDE
        CFG[11]=fem;
#endif
#if defined(RXCAPT_EXPERIMENTAL_PRE_SWITCH) && RXCAPT_EXPERIMENTAL_PRE_SWITCH
        CFG[10]=selector?selector:5u;
#endif
        *last=request[2];
        stream_response(request[2],13u,0u,block,block);return;
    }
    if(op==11u || op==12u || op==14u) {
        uint32_t end=block;
        result=op==11u?rxcapt_stream_claim_batch(STREAM,block,&end):
               op==14u?rxcapt_stream_exchange_batch(STREAM,block,&end):
                       rxcapt_stream_release_batch(STREAM,block);
        if(!result){stream_response(request[2],4u,0xc16u,block,op);return;}
        *last=request[2];stream_clean_state();
        stream_response(request[2],op,0u,block,end);return;
    }
#endif
    if(op==5u)result=rxcapt_stream_claim(STREAM,block);
    else if(op==6u)result=rxcapt_stream_release(STREAM,block);
    else if(op==7u && block==0u)result=rxcapt_stream_request_stop(STREAM);
#if defined(RXCAPT_REUSABLE_STREAM) && RXCAPT_REUSABLE_STREAM
    else if(op==9u || op==10u) {
        volatile uint32_t *meta=(volatile uint32_t *)TERM_META;
        if(meta[3]!=30u || !(STREAM[3]&1u) || STREAM[7]!=STREAM[6] ||
           !rxcapt_stream_dma_idle(STREAM) || (STREAM[8]!=1u && STREAM[8]!=2u)) {
            stream_response(request[2],4u,0xc12u,block,op);return;
        }
        if(op==10u && block==0u) {
            *last=request[2];stream_clean_state();
            stream_response(request[2],10u,0u,STREAM[6],STREAM[8]);return;
        }
        if(op!=9u ||
#if defined(RXCAPT_MULTI_PROFILE) && RXCAPT_MULTI_PROFILE
           !block || !terminal_profile_raw_valid(CFG[3],block) ||
#else
           block<RXCAPT_RAW_SWEEP_MIN || block>RXCAPT_RAW_SWEEP_MAX ||
#endif
           CFG[1]!=2u || CFG[2]!=1u || CFG[4]>5u || CFG[5]>124u) {
            stream_response(request[2],4u,0xc13u,block,op);return;
        }
#if defined(RXCAPT_FAST_TUNE) && RXCAPT_FAST_TUNE
        if(block==CFG[9]){stream_response(request[2],4u,0xc14u,block,op);return;}
        if((block>CFG[9]?block-CFG[9]:CFG[9]-block)>1000u) {
            stream_response(request[2],4u,0xc15u,block,op);return;
        }
        extern uint32_t terminal_fast_request_clock(void);
        terminal_fast_request_clock();
#endif
        CFG[9]=block;*last=request[2];
        /* Clear both old private ring and its AP export before acknowledging
         * REARM, so the consumer cannot mistake the last drained epoch for
         * the next one. Only a fully stopped/drained success reaches here. */
        for(unsigned i=0;i<30u;i++)STREAM[i]=0u;
        stream_clean_state();meta[35]=1u;
        stream_response(request[2],9u,0u,block,meta[32]+1u);return;
    }
#endif
    else if(op==8u && block==0u && (STREAM[3]&1u)) {
        /* AP can observe an old/mixed cache-line snapshot during STOP. Keep
         * the same PARK request pending until RF/DMA teardown has published
         * HELD/FAILED and the actual CP state is drained. Do not advance the
         * command sequence or reject a transiently premature PARK. */
        uint32_t phase=*(volatile uint32_t *)(TERM_META+12u);
        if((phase!=30u && phase!=31u) || STREAM[7]!=STREAM[6] ||
           !rxcapt_stream_dma_idle(STREAM))return;
        *last=request[2];
        stream_clean_state();
        stream_response(request[2],3u,0u,STREAM[6],STREAM[8]);
        terminal_hold();
    }
    if(!result) {
        stream_response(request[2],4u,0xc11u,block,op);return;
    }
    *last=request[2];
    stream_clean_state();
    stream_response(request[2],op,0u,block,op==5u?block%STREAM[2]:STREAM[7]);
}

#if !defined(RXCAPT_REUSABLE_STREAM) || !RXCAPT_REUSABLE_STREAM
void terminal_stream_drain(void) __attribute__((noreturn));
#endif
void terminal_stream_drain(void) {
#ifdef RXCAPT_STREAM_EXPORT_ADDRESS
    stream_clean_state();
#endif
    for(;;) {
        terminal_stream_poll();
#if defined(RXCAPT_REUSABLE_STREAM) && RXCAPT_REUSABLE_STREAM
        volatile uint32_t *meta=(volatile uint32_t *)TERM_META;
        if(meta[35]){meta[35]=0u;return;}
#endif
    }
}
#endif

/* Return only after a fresh NEXT acknowledges the fully exported last burst.
 * The caller has already stopped RF and both DMA channels. STOP parks CP;
 * neither NEXT nor STOP restores the vendor scheduler/IRQ context. */
void terminal_service_next(uint32_t completed) {
    if(!TERM_SERVICE_MAILBOX)terminal_hold();
    response(completed,1u,0u); /* WAIT: buffers remain held until NEXT. */
    for(;;) {
        uint32_t request[8];
        invalidate_request();
        for(unsigned i=0;i<8;i++)request[i]=Q[i];
        invalidate_request();
        unsigned i;
        for(i=0;i<8;i++)if(request[i]!=Q[i])break;
        if(i!=8)continue;
        if(request[0]!=SERVICE_MAGIC || request[1]!=TERM_GENERATION ||
           request[2]!=completed+1u || request[6]!=~request[2] ||
           request[7]!=request[2])continue;
        if(request[4]!=completed ||
           (request[3]!=3u && request[3]!=4u && request[5]) ||
           (request[3]<1u || request[3]>4u)) {
            response(completed,4u,0xc01u);continue;
        }
        if(request[3]==3u && !apply_parameters(request[5])) {
            response(completed,4u,0xc02u);continue;
        }
        if(request[3]==4u && !apply_raw_frequency(request[5])) {
            response(completed,4u,0xc03u);continue;
        }
        if(request[3]==2u) {
            response(request[2],3u,0u);terminal_hold();
        }
        response(request[2],2u,0u); /* RUN: old buffers may now be reused. */
        return;
    }
}
