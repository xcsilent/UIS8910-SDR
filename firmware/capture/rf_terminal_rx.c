#include <stdint.h>
#include "terminal_binding.h"
#include "rfad_off_immediate.h"
#include "rfad_rx_request.h"
#include "rfad_stop.h"
#include "rxcapt_raw_frequency.h"
#include "rxcapt_profile.h"
#include "rxcapt_profile_nv.h"
#if defined(RXCAPT_LOSSY_SCRATCH) && RXCAPT_LOSSY_SCRATCH
#include "rxcapt_lossy_pair.h"
#if !defined(RXCAPT_CONTINUOUS_STREAM) || !RXCAPT_CONTINUOUS_STREAM || SDR_RX_OUTPUT_SLOTS != 6u
#error lossy scratch requires continuous stream and six output slots
#endif
#endif

#define M ((volatile uint32_t *)TERM_META)
#define CFG ((volatile uint32_t *)TERM_CONFIG)
#define R32(a) (*(volatile uint32_t *)(a))
#define R16(a) (*(volatile uint16_t *)(a))
#include "rxcapt_fast_tune.h"

static uint32_t terminal_open_domains(void);
static __attribute__((noinline)) uint32_t terminal_bandwidth_valid(uint32_t value) {
#if defined(RXCAPT_ALLOW_ZERO_BANDWIDTH) && RXCAPT_ALLOW_ZERO_BANDWIDTH
    return value<=5u;
#else
    return value>=1u && value<=5u;
#endif
}
#include "terminal_rxcapt_core.inc"
#if defined(RXCAPT_FAST_TUNE) && RXCAPT_FAST_TUNE
uint32_t terminal_fast_request_clock(void) {
    terminal_fast_stage(8u);return FAST_TRACE[8];
}
#endif
#ifndef RXCAPT_RING_BLOCKS
#define RXCAPT_RING_BLOCKS 1u
#define RXCAPT_RING_DATA_TOTAL_BYTES RXCAPT_FINITE_DATA_BYTES
#define RXCAPT_RING_HEAD_TOTAL_BYTES 24u
#endif
#if RXCAPT_RING_BLOCKS > 1u
extern uint32_t rxcapt_ring_poll_rearm(uint32_t channel, uint32_t is_head,
                                       uint32_t next_slot);
#endif
#if defined(RXCAPT_CONTINUOUS_STREAM) && RXCAPT_CONTINUOUS_STREAM
#if RXCAPT_RING_BLOCKS != 7u
#error continuous stream requires the reviewed seven-slot memory layout
#endif
#ifndef RXCAPT_STREAM_STATE_ADDRESS
#error continuous stream requires an explicit AP-readable state address
#endif
#define STREAM ((volatile uint32_t *)RXCAPT_STREAM_STATE_ADDRESS)
extern uint32_t rxcapt_stream_state_init(volatile uint32_t *,uint32_t);
extern uint32_t rxcapt_stream_complete(volatile uint32_t *,uint32_t,
                                       uint32_t,uint32_t *);
extern uint32_t rxcapt_stream_request_stop_reason(volatile uint32_t *,uint32_t);
extern uint32_t rxcapt_stream_dma_aborted(volatile uint32_t *,uint32_t);
extern uint32_t rxcapt_stream_dma_idle(volatile uint32_t *);
extern void terminal_stream_poll(void);
#if defined(RXCAPT_REUSABLE_STREAM) && RXCAPT_REUSABLE_STREAM
extern void terminal_stream_drain(void);
#else
extern void terminal_stream_drain(void) __attribute__((noreturn));
#endif
#define STREAM_STOP 1u
#define STREAM_FULL 2u
#define STREAM_REASON_HOST 1u
#define STREAM_REASON_FULL 2u
#define STREAM_REASON_TIMEOUT 3u
#define STREAM_REASON_DMA_ERROR 4u
#define STREAM_REASON_REARM_ERROR 5u
/* The live frame counter measured about 1000 units/s. The AP accepts at
 * most 180 s plus bounded drain time; leave margin for that entire session.
 * AP STOP remains the normal deadline. This is an independent CP backstop,
 * not a sample-clock calibration or a promise of uninterrupted samples. */
#define STREAM_MAX_FRAME_UNITS 200000u
#define STREAM_MAX_POLLS 50000000u
#if defined(RXCAPT_USB_UNTIL_STOP) && RXCAPT_USB_UNTIL_STOP
static __attribute__((noinline)) uint32_t terminal_stream_timeout_expired(uint32_t elapsed,
    uint32_t *activity,uint32_t *previous_cursor) {
    uint32_t cursor=*(volatile uint32_t *)(TERM_META+31u*4u);
    /* RF elapsed frame units wrap at the native cycle period. A wrap must
     * not be mistaken for a many-day idle interval. Only accepted commands
     * advance this cursor; stale/invalid requests do not renew the guard. */
    if(cursor!=*previous_cursor || elapsed<*activity) {
        *previous_cursor=cursor;*activity=elapsed;
    }
    return elapsed-*activity>=5000u;
}
#else
static __attribute__((noinline)) uint32_t terminal_stream_timeout_expired(uint32_t elapsed) {
    return elapsed>=STREAM_MAX_FRAME_UNITS;
}
#endif
static void clean_range(uint32_t a,uint32_t n);
#ifdef RXCAPT_STREAM_EXPORT_ADDRESS
extern void terminal_stream_publish(void);
#endif
static void stream_sync(void) {
#ifdef RXCAPT_STREAM_EXPORT_ADDRESS
    terminal_stream_publish();
#else
    clean_range((uint32_t)STREAM,30u*4u);
#endif
}
#endif
extern void terminal_hold(void) __attribute__((noreturn));
extern void terminal_service_next(uint32_t completed);

enum { T_READY=1,T_WAIT=10,T_CLAIMED=20,T_FORCE_IDLE=21,T_PREPARE=22,T_PREPARED=23,
       T_ARM=24,T_EVENT=25,T_RX=26,T_POLL=27,T_STOP_RF=28,T_STOP_DMA=29,T_HELD=30,
       T_FAILED=31,T_PINNED=32,T_WAIT_EXPIRED=33 };
static void failed(uint32_t error,uint32_t pinned) __attribute__((noreturn));

static uint32_t raw_read(void *c,uint32_t a,unsigned n) {
    (void)c;
    return n==1?*(volatile uint8_t *)a:n==2?R16(a):R32(a);
}
static void raw_write(void *c,uint32_t a,uint32_t v,unsigned n) {
    (void)c;
    if(n==1)*(volatile uint8_t *)a=(uint8_t)v;
    else if(n==2)R16(a)=(uint16_t)v;
    else R32(a)=v;
}
static void clean_range(uint32_t a,uint32_t n) {
    for(uint32_t line=a&~31u;line<a+n;line+=32)
        __asm__ volatile("mcr p15,0,%0,c7,c10,1"::"r"(line):"memory");
    __asm__ volatile("dsb sy":::"memory");
}
static void publish(uint32_t phase,uint32_t error,uint32_t next) {
    volatile uint32_t *out=(volatile uint32_t *)TERM_PROGRESS;
    uint32_t seq=(M[24]+2u)&~1u,cpsr;
    M[3]=phase;M[4]=error;M[24]=seq;
    __asm__ volatile("mrs %0,cpsr":"=r"(cpsr));
    out[2]=seq|1u;
    __asm__ volatile("dmb sy":::"memory");
    out[0]=TERM_MAGIC;out[1]=TERM_GENERATION;out[3]=phase;out[4]=error;out[5]=next;
    out[6]=phase==T_HELD?STATE->data_valid_bytes:0;
    out[7]=phase==T_HELD?STATE->head_valid_bytes:0;
    out[8]=STATE->data_channel;out[9]=STATE->head_channel;out[10]=STATE->phase;
    out[11]=M[6];out[12]=M[10];out[13]=M[15];out[14]=M[11];out[15]=cpsr;
    __asm__ volatile("dmb sy":::"memory");
    out[2]=seq;clean_range(TERM_PROGRESS,64);
}
#include "rxcapt_stream_timing.h"
#include "rxcapt_digital_profile.h"
#include "rxcapt_rf_core_snapshot.h"
#include "rxcapt_rf_phase_log.h"
#include "rxcapt_rf_target_register_snapshot.h"
#include "rxcapt_rf_status_trace.h"
#include "rxcapt_fem_override.h"
#include "rxcapt_rf_fixed_config_probe.h"
#include "rxcapt_rf_timer_probe.h"
#include "rxcapt_rf_coefficient_probe.h"
static void proof(void) {
    volatile uint32_t *p=(volatile uint32_t *)TERM_PROOF;
    for(unsigned i=0;i<128;i++)p[i]=0;
    p[0]=TERM_MAGIC;p[1]=TERM_GENERATION;p[2]=M[3];p[3]=M[4];
    p[4]=M[6];p[5]=STATE->data_channel;p[6]=STATE->head_channel;p[7]=STATE->done_mask;
    for(unsigned i=0;i<32;i++)p[8+i]=M[i];
    for(unsigned i=0;i<11;i++)p[40+i]=((volatile uint32_t *)0x804ed5acu)[i];
    for(unsigned i=0;i<10;i++)p[51+i]=((volatile uint32_t *)0x804ed5f8u)[i];
    p[61]=M[32];
    p[62]=CFG[3]|(CFG[4]<<16)|(CFG[5]<<19);
    p[63]=0x50524131u; /* versioned per-capture parameter metadata */
    for(unsigned i=0;i<32;i++)p[64+i]=((volatile uint32_t *)TERM_PLAN)[i];
    for(unsigned i=0;i<16;i++)p[96+i]=((volatile uint32_t *)TERM_EVENT_OUT)[i];
    for(unsigned i=0;i<16;i++)p[112+i]=((volatile uint32_t *)TERM_RX_OUT)[i];
    volatile uint32_t *exported=(volatile uint32_t *)TERM_STATE_EXPORT;
    for(unsigned i=0;i<107;i++)exported[i]=((volatile uint32_t *)STATE)[i];
    clean_range(TERM_STATE_EXPORT,107u*4u);
    clean_range(TERM_PROOF,512);
}

/* The verified TDD first-RXON path uses down+0xcc when its previous event is
 * -1, otherwise down+0x268. Preserve the exact frequency command words now,
 * before RF-off resets event state. AP reads this only after HELD. */
static void frequency_evidence(void) __attribute__((noinline,optimize("Os")));
static void frequency_evidence(void) {
    volatile uint32_t *f=(volatile uint32_t *)TERM_FREQUENCY_EXPORT;
    uint32_t anchor=terminal_profile_anchor(CFG[3]);
    uint32_t cfg=0x804eda30u+0x1754u; /* First FDD mode2 RXON, bound by CP replay. */
#if defined(RXCAPT_MULTI_PROFILE) && RXCAPT_MULTI_PROFILE
    if(CFG[3]>=36200u) cfg=0x804eda30u+(M[33]==0xffffffffu?0xccu:0x268u);
#endif
    uint32_t lo=R32(cfg+16u),hi=R32(cfg+20u);
    f[0]=0x46525131u;f[1]=TERM_GENERATION;f[2]=M[32];f[3]=CFG[9];
    f[4]=CFG[3]|(CFG[4]<<16)|(CFG[5]<<19);f[5]=anchor;
    f[6]=CFG[9]?CFG[9]:anchor;
    f[7]=R32(0x804ed5c8u);f[8]=R32(0x804ed604u);
    f[9]=cfg;f[10]=lo;f[11]=hi;f[12]=0;f[13]=0;f[14]=0;f[15]=M[33];
    if(!(lo&3u) && !(hi&3u) && lo!=hi &&
       ((lo>=0x25101260u && lo<=0x2510157cu)||(lo>=0x25102260u && lo<=0x2510257cu)) &&
       ((hi>=0x25101260u && hi<=0x2510157cu)||(hi>=0x25102260u && hi<=0x2510257cu))) {
        f[12]=R32(lo);f[13]=R32(hi);
        f[14]=f[12]==(0x00580000u|(f[6]&65535u)) &&
              f[13]==(0x00080000u|(f[6]>>16));
    }
    clean_range(TERM_FREQUENCY_EXPORT,64);
}

/* RF/L1 can expose an incomplete profile on an early FCP opportunity. Keep
 * the hook armed for a bounded number of callbacks, but never open a domain
 * or claim the transaction until every field matches the requested channel. */
static void retry_profile_or_expire(uint32_t error,uint32_t address,
                                    uint32_t detail) {
    M[25]=address;M[26]=detail;
    if(M[2])failed(error,1);
    if(M[5]>=320u || M[7]) {
        M[1]=0;publish(T_WAIT_EXPIRED,error,address);proof();
    } else publish(T_WAIT,error,address);
}

/* Preserve a read-only snapshot when pre-claim DMA ownership never becomes
 * idle. TERM_PLAN is unused before claim and is copied into the proof block. */
static void snapshot_preclaim_dma_wait(uint32_t base,uint32_t control,
                                       uint32_t sgconf) {
    volatile uint32_t *snapshot=(volatile uint32_t *)TERM_PLAN;
    volatile uint32_t *descriptor=(volatile uint32_t *)TERM_EVENT_OUT;
    volatile uint32_t *rxcap=(volatile uint32_t *)TERM_RX_OUT;
    static const uint8_t rxcap_offsets[16]={
        0x00,0x04,0x08,0x0c,0x10,0x14,0x20,0x24,
        0x2c,0x30,0x34,0x38,0x3c,0x40,0x44,0x48
    };
    M[25]=base;M[26]=control;M[27]=sgconf;
    M[28]=R32(RXCAPT_DMA_ALLOCATOR_ADDRESS);
    M[29]=R16(RXCAPT_CAPTURE_BITMAP_ADDRESS);
    M[30]=R32(0x804689a4u);
    M[31]=R16(0x8048df56u);
    /* These output areas are unused until the pre-claim gate passes. Preserve
       the busy channel's descriptor so its firmware owner can be identified. */
    descriptor[0]=base;
    descriptor[1]=control;
    descriptor[2]=R32(base+0x04u);
    descriptor[3]=R32(base+0x08u);
    descriptor[4]=R32(base+0x0cu);
    descriptor[5]=R32(base+0x10u);
    descriptor[6]=R32(base+0x14u);
    descriptor[7]=sgconf;
    uint32_t zsp_power=R32(0x500a0024u);
    uint32_t phy_power=R32(0x500a0028u);
    descriptor[8]=zsp_power;
    descriptor[9]=phy_power;
    uint32_t channel=(base-0x22000040u)>>6;
    /* These are current CP BIN runtime addresses. The AXF globals have a
       different layout and must not be used for live diagnostics. */
    descriptor[10]=R32(0x80476754u+8u*channel);
    descriptor[11]=R32(0x80476758u+8u*channel);
    descriptor[12]=*(volatile uint8_t *)0x804689a1u;
    descriptor[13]=R32(0x22000018u);
    descriptor[14]=R32(0x2200001cu);
    descriptor[15]=R16(RXCAPT_DMA_ALLOCATOR_ADDRESS+2u);
    /* RXCAPT lives in the PHY domain. Never touch it while that domain is
       gated; an all-ones block marks that the read was intentionally skipped. */
    if(zsp_power==3u && phy_power==3u) {
        for(unsigned i=0;i<16;i++)rxcap[i]=R32(0x27000000u+rxcap_offsets[i]);
    } else {
        for(unsigned i=0;i<16;i++)rxcap[i]=0xffffffffu;
    }
    for(unsigned ch=0;ch<12;ch++) {
        uint32_t channel_base=dma_channel_base(ch);
        snapshot[ch*2]=R32(channel_base);
        snapshot[ch*2+1]=R32(channel_base+0x18u);
    }
    snapshot[24]=R32(RXCAPT_DMA_ALLOCATOR_ADDRESS);
    snapshot[25]=R16(RXCAPT_CAPTURE_BITMAP_ADDRESS);
    snapshot[26]=R32(0x804689a4u);
    snapshot[27]=R16(0x8048df56u);
    snapshot[28]=R32(0x500a0024u);
    snapshot[29]=R32(0x500a0028u);
    snapshot[30]=M[5];
    snapshot[31]=0x444d4131u; /* "DMA1" */
}

/* Capture the documented RXCAPT control/status words on both sides of RF
 * initialization. TERM_PLAN is unused until the RX request is planned. */
static void snapshot_rxcapt_registers(unsigned first_word) {
    static const uint8_t offsets[16]={
        0x00,0x04,0x08,0x0c,0x10,0x14,0x20,0x24,
        0x2c,0x30,0x34,0x38,0x3c,0x40,0x44,0x48
    };
    volatile uint32_t *snapshot=(volatile uint32_t *)TERM_PLAN;
    for(unsigned i=0;i<16;i++)snapshot[first_word+i]=R32(0x27000000u+offsets[i]);
}

/* Same verified ZSP-then-PHY request ordering as the finite controller,
 * replacing its two unbounded vendor polls with finite status budgets. */
static uint32_t terminal_open_domains(void) {
    uint32_t z=R32(0x500a0024u),p=R32(0x500a0028u);
    if((z!=2 && z!=3)||(p!=2 && p!=3))return 0x900u;
    if(z==2) {
        R32(0x500a0054u)=6;
        unsigned i;
        for(i=0;i<8192;i++)if(R32(0x500a0024u)==3)break;
        if(i==8192)return 0x901u;
    }
    if(p==2) {
        R32(0x500a000cu)=R32(0x500a000cu)|2u;
        unsigned i;
        for(i=0;i<8192;i++)if(R32(0x500a0028u)==3)break;
        if(i==8192)return 0x902u;
    }
    R32(0x80476c40u)=R32(0x80476c40u)|0x2000u;
    M[18]=R32(0x500a0024u);M[19]=R32(0x500a0028u);
    return M[18]==3 && M[19]==3?1u:0x903u;
}

static enum rfad_frame_time_result force_idle(const struct rf_bus *b,uint32_t card) {
    const uint32_t nv=0x804f42b8u,cursor=0x804ed48cu;
    R32(0x25100000u)=R32(0x25100000u)&~3u;
    rfad_reset_memory(b,cursor,1);
    uint32_t gpio=(uint32_t)R16(nv+0xd2u)&R16(nv+0xd0u);
    if(card)gpio|=R32(nv+0xe4u);
    R32(0x25100008u)=gpio;
    rfad_reset_memory(b,cursor,2);
    R32(0x25100008u)=gpio|0x10000u;
    R32(cursor+0x2cu)=(uint32_t)R16(nv+0xd6u)&R16(nv+0xd4u);
    const struct rfad_off_immediate_context c={0x804ed5acu,0x804ed5f8u,0x804ed620u,nv,cursor};
    uint32_t completed=0;
    enum rfad_frame_time_result result=rfad_off_immediate_bounded(b,&c,card,4096,&completed);
    M[11]=completed;
    if(result==RFAD_FRAME_TIME_OK) {
        gpio=(uint32_t)R16(nv+0xd6u)&R16(nv+0xd4u);
        if(card)gpio|=R32(nv+0xe4u);
        R32(0x25100008u)=gpio;
    }
    __asm__ volatile("dsb sy":::"memory");
    return result;
}

static void failed(uint32_t error,uint32_t pinned) {
    publish(pinned?T_PINNED:T_FAILED,error,0);proof();terminal_hold();
}

static void transaction(void) __attribute__((noinline));
static void transaction(void) {
    const struct rf_bus bus={0,raw_read,raw_write};
    terminal_rf_status_trace(0u);
    terminal_fast_begin();
    uint32_t card=R16(0x804ed56cu)?1u:0u;
    publish(T_FORCE_IDLE,0,0x25100000u);
    if(force_idle(&bus,card)!=RFAD_FRAME_TIME_OK)failed(0xa01u,1);
    terminal_fast_stage(10u);
    R16(0x804ed56cu)=0;
    publish(T_PREPARE,0,RXCAPT_RF_LTE_INIT_DYLOAD_ENTRY);
    uint32_t result=prepare();
    if(result!=RXCAPT_PHASE_PREPARED) {
        /* Preserve the three read-only RXCAPT control values behind 0x406.
           PREPARE has already read them; this snapshot identifies which
           precondition blocked channel allocation without further writes. */
        if(result==0x406u) {
            snapshot_rxcapt_registers(16);
            M[25]=R32(0x27000000u);
            M[26]=R32(0x27000004u);
            M[27]=R32(0x27000010u);
        }
        failed(0xb000u|result,1);
    }
    publish(T_PREPARED,0,0);
    terminal_rf_status_trace(1u);
#if defined(RXCAPT_MULTI_PROFILE) && RXCAPT_MULTI_PROFILE
    /* Never let an absent NV row reuse a previous route/calibration. */
    uint32_t nv_row=terminal_profile_nv_row(CFG[3]);
    if(!nv_row) failed(0xa0bu,1u);
    /* RF has been forced idle and PREPARE completed; no RX events or capture
     * DMA have been armed. Only the opt-in experiment touches its template. */
    if(terminal_fem_begin(nv_row-1u))failed(0xa0cu,1u);
#endif
    terminal_fast_stage(11u);
    terminal_digital_profile(1u);
    /* Mark every selected DATA/HEAD slot before arming DMA. Unfilled ring
       tails therefore remain detectable in the host audit. */
    for(unsigned i=0;i<RXCAPT_RING_DATA_TOTAL_BYTES/4u;i++)
        ((volatile uint32_t *)0x80960000u)[i]=0xa55aa55au;
    for(unsigned i=0;i<RXCAPT_RING_HEAD_TOTAL_BYTES/4u;i++)
        ((volatile uint32_t *)0x8096ff00u)[i]=0xa55aa55au;
    clean_range(0x80960000u,RXCAPT_RING_DATA_TOTAL_BYTES);
    clean_range(0x8096ff00u,RXCAPT_RING_HEAD_TOTAL_BYTES);
    struct rfad_frame_time start;
    if(rfad_read_frame_time_bounded(&bus,0,4096,&start)!=RFAD_FRAME_TIME_OK)failed(0xa02u,1);
    struct rfad_rx_request_config c;
    for(unsigned i=0;i<9;i++)((uint32_t *)&c)[i]=CFG[i];
    c.card=0;c.target_subframe=(start.ssfn+2u)%10u;
    struct rfad_rx_request_plan *plan=(struct rfad_rx_request_plan *)TERM_PLAN;
    if(rfad_rx_request_plan(&c,plan,start.cycle,start.ssfn)!=1)failed(0xa03u,1);
    M[15]=start.ssfn;M[21]=start.ssfn;M[22]=start.cycle;
#if defined(RXCAPT_RF_PRE_RXON_CONTEXT) && RXCAPT_RF_PRE_RXON_CONTEXT
    terminal_rf_pre_rxon_snapshot_begin();
#endif
#if defined(RXCAPT_CONTINUOUS_STREAM) && RXCAPT_CONTINUOUS_STREAM
#if defined(RXCAPT_REUSABLE_STREAM) && RXCAPT_REUSABLE_STREAM
    if(M[32]==1u)M[31]=0u;
#else
    M[31]=0u;
#endif
    if(!rxcapt_stream_state_init(STREAM,
#if defined(RXCAPT_LOSSY_SCRATCH) && RXCAPT_LOSSY_SCRATCH
        SDR_RX_OUTPUT_SLOTS
#else
        RXCAPT_RING_BLOCKS
#endif
        ))failed(0xa0au,1u);
    stream_sync();
#endif
    publish(T_ARM,0,RXCAPT_CAL_CAPTURE_ENTRY);
#if !defined(RXCAPT_FAST_TUNE) || !RXCAPT_FAST_TUNE
    if(arm()!=RXCAPT_PHASE_RUNNING)failed(0xa04u,1);
#endif
    terminal_rf_phase_log_begin();
    terminal_rf_phase_log(1u,0u,0u);
    publish(T_EVENT,0,TERM_RF_EVENT_ENTRY);
    ((void (*)(const void *,void *,uint32_t,uint32_t))TERM_RF_EVENT_ENTRY)(
        plan->event_words,(void *)TERM_EVENT_OUT,0u,0u);
    M[6]=1;
    terminal_rf_phase_log(2u,0u,0u);
    if(CFG[9])R32(0x804ed5c8u)=CFG[9];
    M[33]=R32(0x804ed4d4u);
    terminal_rf_phase_log(3u,0u,0u);
#if defined(RXCAPT_RF_PRE_RXON_CONTEXT) && RXCAPT_RF_PRE_RXON_CONTEXT
    terminal_rf_core_snapshot_pre_rxon();
#endif
    publish(T_RX,0,TERM_RF_RX_ENTRY);
    terminal_rf_status_trace(2u);
    ((void (*)(const void *,void *,uint32_t,uint32_t))TERM_RF_RX_ENTRY)(
        plan->rx_words,(void *)TERM_RX_OUT,20u,0u);
    M[6]=2;
    terminal_rf_status_trace(3u);
    terminal_rf_phase_log(4u,0u,0u);
    terminal_fast_stage(12u);
#if defined(RXCAPT_FAST_TUNE) && RXCAPT_FAST_TUNE
    uint32_t fast_ready=terminal_fast_wait_ready();
    if(fast_ready!=1u){FAST_TRACE[6]=fast_ready;clean_range((uint32_t)FAST_TRACE,128u);failed(fast_ready,1u);}
    if(arm()!=RXCAPT_PHASE_RUNNING)failed(0xa04u,1);
    terminal_fast_stage(14u);
#endif
    frequency_evidence();
    terminal_digital_profile(2u);
    proof();publish(T_POLL,0,0x22000000u);
    volatile uint32_t *data=(volatile uint32_t *)dma_channel_base(STATE->data_channel);
    volatile uint32_t *head=(volatile uint32_t *)dma_channel_base(STATE->head_channel);
    int complete=0;
    uint32_t data_blocks=0,head_blocks=0;
#if defined(RXCAPT_CONTINUOUS_STREAM) && RXCAPT_CONTINUOUS_STREAM
    uint32_t data_seen=0u,head_seen=0u;
#if defined(RXCAPT_LOSSY_SCRATCH) && RXCAPT_LOSSY_SCRATCH
    struct rxcapt_lossy_pair pair;
    uint32_t stop_polls=0u;
    pair.active=0u;
    if(rxcapt_lossy_adopt_initial(STREAM,&pair)!=RX_LOSSY_ARM)failed(0xa0cu,1u);
#endif
    terminal_stream_timing_begin();
    terminal_rf_core_snapshot_begin();
#if defined(RXCAPT_RF_TARGET_REGISTER_SNAPSHOT) && RXCAPT_RF_TARGET_REGISTER_SNAPSHOT
    terminal_rf_target_register_snapshot_begin();
#endif
#if defined(RXCAPT_RF_FIXED_CONFIG_PROBE) && RXCAPT_RF_FIXED_CONFIG_PROBE
    terminal_rf_fixed_config_probe_begin();
#endif
#if defined(RXCAPT_RF_COEFFICIENT_PROBE) && RXCAPT_RF_COEFFICIENT_PROBE
    terminal_rf_coefficient_probe_begin();
#endif
    terminal_stream_timing_record(&bus,3u,0u);
#if defined(RXCAPT_USB_UNTIL_STOP) && RXCAPT_USB_UNTIL_STOP
    uint32_t watchdog_activity=0,watchdog_cursor=*(volatile uint32_t *)(TERM_META+31u*4u);
    uint32_t poll_cursor=watchdog_cursor;
#endif
    for(uint32_t i=0;i<STREAM_MAX_POLLS;i++) {
        uint32_t ds=data[6],hs=head[6],dc=data[4],hc=head[4];
        M[10]=i+1u;M[8]=dc;M[9]=hc;M[16]=ds;M[17]=hs;
        if((ds|hs)&DMA_RESPONSE_ERROR_MASK) {
            rxcapt_stream_request_stop_reason(STREAM,STREAM_REASON_DMA_ERROR);
            stream_sync();
            break;
        }
#if defined(RXCAPT_STREAM_FAST_MAILBOX_POLL) && RXCAPT_STREAM_FAST_MAILBOX_POLL
        if(!(i&7u))terminal_stream_poll();
#else
        if(!(i&63u))terminal_stream_poll();
#endif
#if defined(RXCAPT_LOSSY_SCRATCH) && RXCAPT_LOSSY_SCRATCH
        uint32_t stream_changed=0u;
        if(!data_seen && !dc && (ds&DMA_COUNT_FINISH_STATUS) && !(ds&DMA_RUN_MASK)) {
            ++data_blocks;STATE->data_callback_count=data_blocks;STATE->data_event_mask|=1u;
            if(rxcapt_lossy_complete(STREAM,&pair,0u)==RX_LOSSY_ERROR) {
                rxcapt_stream_request_stop_reason(STREAM,STREAM_REASON_DMA_ERROR);stream_sync();break;
            }
            data_seen=1u;stream_changed=1u;
        }
        if(!head_seen && !hc && (hs&DMA_COUNT_FINISH_STATUS) && !(hs&DMA_RUN_MASK)) {
            ++head_blocks;STATE->head_callback_count=head_blocks;STATE->head_event_mask|=1u;
            if(rxcapt_lossy_complete(STREAM,&pair,1u)==RX_LOSSY_ERROR) {
                rxcapt_stream_request_stop_reason(STREAM,STREAM_REASON_DMA_ERROR);stream_sync();break;
            }
            head_seen=1u;stream_changed=1u;
        }
        if(data_seen && head_seen && !pair.active && !(STREAM[3]&STREAM_STOP)) {
            uint32_t next_slot;
            if(rxcapt_lossy_begin(STREAM,&pair,6u,&next_slot)!=RX_LOSSY_ARM) {
                rxcapt_stream_request_stop_reason(STREAM,STREAM_REASON_REARM_ERROR);stream_sync();break;
            }
            /* Reservation stays active even if one arm fails. The teardown
             * path stops both channels before clearing ownership. */
            stream_sync();
            stream_changed=0u;
            if(!rxcapt_lossy_arm_reserved(&pair,STATE->data_channel,STATE->head_channel,
                                         rxcapt_ring_poll_rearm)) {
                rxcapt_stream_request_stop_reason(STREAM,STREAM_REASON_REARM_ERROR);stream_sync();break;
            }
            data_seen=head_seen=0u;
        }
        /* No mailbox service runs between the two completion checks and
         * reservation above. Publish their combined state once, before DMA
         * rearm, or publish a partial/STOP completion here. Private ownership
         * barriers and every error-path publication remain unchanged. */
        if(stream_changed)stream_sync();
#else
        if(!data_seen && !dc && (ds&DMA_COUNT_FINISH_STATUS) &&
           !(ds&DMA_RUN_MASK)) {
            uint32_t next_slot=0xffffffffu;
            terminal_stream_timing_record(&bus,1u,data_blocks);
            ++data_blocks;STATE->data_callback_count=data_blocks;
            STATE->data_event_mask|=1u;
            uint32_t action=rxcapt_stream_complete(
                STREAM,0u,STREAM[4],&next_slot);
            if(action==1u) {
                if(!rxcapt_ring_poll_rearm(STATE->data_channel,0u,next_slot)) {
                    rxcapt_stream_request_stop_reason(
                        STREAM,STREAM_REASON_REARM_ERROR);
                    stream_sync();
                    break;
                }
            } else if(action==2u || action==3u) data_seen=1u;
            else {
                rxcapt_stream_request_stop_reason(
                    STREAM,STREAM_REASON_DMA_ERROR);
                stream_sync();
                break;
            }
            stream_sync();
            if(data_blocks==1u && head_blocks) {
                terminal_fast_stage(15u);
                terminal_rf_phase_log(5u,data_blocks,head_blocks);
                terminal_rf_core_snapshot(data_blocks,head_blocks);
            }
        }
        if(!head_seen && !hc && (hs&DMA_COUNT_FINISH_STATUS) &&
           !(hs&DMA_RUN_MASK)) {
            uint32_t next_slot=0xffffffffu;
            terminal_stream_timing_record(&bus,2u,head_blocks);
            ++head_blocks;STATE->head_callback_count=head_blocks;
            STATE->head_event_mask|=1u;
            uint32_t action=rxcapt_stream_complete(
                STREAM,1u,STREAM[5],&next_slot);
            if(action==1u) {
                if(!rxcapt_ring_poll_rearm(STATE->head_channel,1u,next_slot)) {
                    rxcapt_stream_request_stop_reason(
                        STREAM,STREAM_REASON_REARM_ERROR);
                    stream_sync();
                    break;
                }
            } else if(action==2u || action==3u) head_seen=1u;
            else {
                rxcapt_stream_request_stop_reason(
                    STREAM,STREAM_REASON_DMA_ERROR);
                stream_sync();
                break;
            }
            stream_sync();
            if(head_blocks==1u && data_blocks) {
                terminal_fast_stage(15u);
                terminal_rf_phase_log(5u,data_blocks,head_blocks);
                terminal_rf_core_snapshot(data_blocks,head_blocks);
            }
        }
#endif
        if((STREAM[3]&STREAM_STOP) && rxcapt_stream_dma_idle(STREAM)) {
            complete=1;
            break;
        }
#if defined(RXCAPT_LOSSY_SCRATCH) && RXCAPT_LOSSY_SCRATCH
        if(rxcapt_lossy_stop_expired(STREAM[3]&STREAM_STOP,&stop_polls)) {
            /* Leave reservations intact until restore_after_stop confirms
             * both channels stopped. Preserve the original STOP reason. */
            break;
        }
#endif
        if(!(i&63u)) {
#if defined(RXCAPT_USB_UNTIL_STOP) && RXCAPT_USB_UNTIL_STOP
            uint32_t cursor=*(volatile uint32_t *)(TERM_META+31u*4u);
            if(cursor!=poll_cursor) {poll_cursor=cursor;i=0;}
#endif
            struct rfad_frame_time now;
            if(rfad_read_frame_time_bounded(&bus,0,64,&now)==RFAD_FRAME_TIME_OK) {
                M[15]=now.ssfn;
                int32_t elapsed=(int32_t)((((uint32_t)now.cycle-start.cycle)&1023u)*10240u)+
                                (int32_t)now.ssfn-(int32_t)start.ssfn;
                if(terminal_stream_timeout_expired((uint32_t)elapsed
#if defined(RXCAPT_USB_UNTIL_STOP) && RXCAPT_USB_UNTIL_STOP
                    ,&watchdog_activity,&watchdog_cursor
#endif
                    ) &&
                   !(STREAM[3]&STREAM_STOP)) {
                    rxcapt_stream_request_stop_reason(
                        STREAM,STREAM_REASON_TIMEOUT);
                    stream_sync();
                }
            }
        }
    }
    if(!complete && !(STREAM[3]&STREAM_STOP)) {
        rxcapt_stream_request_stop_reason(STREAM,STREAM_REASON_TIMEOUT);
        stream_sync();
    }
    terminal_stream_timing_record(&bus,4u,data_blocks);
    terminal_stream_timing_finish();
#else
    for(uint32_t i=0;i<250000u;i++) {
        uint32_t ds=data[6],hs=head[6],dc=data[4],hc=head[4];
        M[10]=i+1;M[8]=dc;M[9]=hc;M[16]=ds;M[17]=hs;
        if((ds|hs)&DMA_RESPONSE_ERROR_MASK)break;
#if RXCAPT_RING_BLOCKS > 1u
        if(data_blocks<RXCAPT_RING_BLOCKS && !dc &&
           (ds&DMA_COUNT_FINISH_STATUS) && !(ds&DMA_RUN_MASK)) {
            ++data_blocks;
            STATE->data_callback_count=data_blocks;
            STATE->data_event_mask|=1u;
            if(data_blocks<RXCAPT_RING_BLOCKS) {
                if(!rxcapt_ring_poll_rearm(STATE->data_channel,0u,data_blocks))
                    failed(0xa08u,1u);
            } else {
                STATE->done_mask|=1u;
                STATE->data_valid_bytes=RXCAPT_RING_DATA_TOTAL_BYTES;
            }
        }
        if(head_blocks<RXCAPT_RING_BLOCKS && !hc &&
           (hs&DMA_COUNT_FINISH_STATUS) && !(hs&DMA_RUN_MASK)) {
            ++head_blocks;
            STATE->head_callback_count=head_blocks;
            STATE->head_event_mask|=1u;
            if(head_blocks<RXCAPT_RING_BLOCKS) {
                if(!rxcapt_ring_poll_rearm(STATE->head_channel,1u,head_blocks))
                    failed(0xa09u,1u);
            } else {
                STATE->done_mask|=2u;
                STATE->head_valid_bytes=RXCAPT_RING_HEAD_TOTAL_BYTES;
            }
        }
        if(data_blocks==RXCAPT_RING_BLOCKS &&
           head_blocks==RXCAPT_RING_BLOCKS) {complete=1;break;}
#else
        if(!dc && !hc && (ds&DMA_COUNT_FINISH_STATUS) && (hs&DMA_COUNT_FINISH_STATUS) &&
           !(ds&DMA_RUN_MASK) && !(hs&DMA_RUN_MASK)){complete=1;break;}
#endif
        if(!(i&63u)) {
            struct rfad_frame_time now;
            if(rfad_read_frame_time_bounded(&bus,0,64,&now)==RFAD_FRAME_TIME_OK) {
                M[15]=now.ssfn;
                uint32_t elapsed=(((uint32_t)now.cycle-start.cycle)&1023u)*10240u+now.ssfn-start.ssfn;
                if(elapsed>=6u*RXCAPT_RING_BLOCKS)break;
            }
        }
    }
#endif
    terminal_digital_profile(3u);
    publish(T_STOP_RF,0,0x25100000u);
    terminal_rf_status_trace(4u);
    terminal_fast_stage(16u);
    if(force_idle(&bus,0)!=RFAD_FRAME_TIME_OK)failed(0xa05u,1);
    /* Restore template only after RF stop is confirmed. Failure paths above
     * remain pinned with active recovery state, never return to drain/REARM. */
    if(terminal_fem_end())failed(0xa0du,1u);
    terminal_rf_status_trace(5u);
    publish(T_STOP_DMA,0,0x22000000u);
    STATE->phase=RXCAPT_PHASE_STOPPING;
    if(complete) {
#if RXCAPT_RING_BLOCKS > 1u
        STATE->done_mask=3u;
#if defined(RXCAPT_CONTINUOUS_STREAM) && RXCAPT_CONTINUOUS_STREAM
        uint32_t ready=STREAM[6]-STREAM[7];
        if(ready>RXCAPT_RING_BLOCKS)ready=RXCAPT_RING_BLOCKS;
        STATE->data_valid_bytes=ready*RXCAPT_FINITE_DATA_BYTES;
        STATE->head_valid_bytes=ready*24u;
#else
        STATE->data_valid_bytes=RXCAPT_RING_DATA_TOTAL_BYTES;
        STATE->head_valid_bytes=RXCAPT_RING_HEAD_TOTAL_BYTES;
#endif
#else
        STATE->done_mask=3;STATE->data_valid_bytes=RXCAPT_FINITE_DATA_BYTES;STATE->head_valid_bytes=24;
#endif
    }
    if(!restore_after_stop(STATE,(uint32_t)complete))failed(0xa06u,1);
    /* The core restores the old digital profile. Explicitly stop RX again
       while CP retains ownership; analog RF/events have already been shut. */
    rfad_txrx_rx_stop(&bus);
#if defined(RXCAPT_CONTINUOUS_STREAM) && RXCAPT_CONTINUOUS_STREAM
    uint32_t stream_reason=STREAM[8];
    uint32_t stream_ok=complete &&
        (stream_reason==STREAM_REASON_HOST || stream_reason==STREAM_REASON_FULL);
    if(!complete) {
        uint32_t reason=STREAM[8]?STREAM[8]:STREAM_REASON_DMA_ERROR;
        rxcapt_stream_dma_aborted(STREAM,reason);
    }
    stream_sync();
    if(stream_ok && STATE->phase==RXCAPT_PHASE_HELD) {
        publish(T_HELD,0,0);
    } else {
        STATE->phase=RXCAPT_PHASE_FAILED;
        STATE->error=0xa07u;
        publish(T_FAILED,0xa07u,STREAM[8]);
    }
    proof();
#if defined(RXCAPT_RF_CODE_SNAPSHOT) && RXCAPT_RF_CODE_SNAPSHOT
    if(stream_ok || STATE->phase==RXCAPT_PHASE_FAILED)terminal_rf_code_snapshot();
#endif
#if defined(RXCAPT_RF_TIMER_PROBE) && RXCAPT_RF_TIMER_PROBE
    if(stream_ok && stream_reason==STREAM_REASON_HOST)terminal_rf_timer_probe();
#endif
#if defined(RXCAPT_RF_COEFFICIENT_PROBE) && RXCAPT_RF_COEFFICIENT_PROBE
    if(stream_ok && stream_reason==STREAM_REASON_HOST)terminal_rf_coefficient_probe();
#endif
#if defined(RXCAPT_RF_TARGET_REGISTER_SNAPSHOT) && RXCAPT_RF_TARGET_REGISTER_SNAPSHOT
    if(stream_ok && (stream_reason==STREAM_REASON_HOST ||
                     stream_reason==STREAM_REASON_FULL))
        terminal_rf_target_register_snapshot();
#endif
#if defined(RXCAPT_RF_FIXED_CONFIG_PROBE) && RXCAPT_RF_FIXED_CONFIG_PROBE
    if(stream_ok && (stream_reason==STREAM_REASON_HOST || stream_reason==STREAM_REASON_FULL))
        terminal_rf_fixed_config_probe();
#endif
    terminal_fast_stage(17u);
    terminal_stream_drain();
#else
    if(complete && STATE->phase==RXCAPT_PHASE_HELD) {
        publish(T_HELD,0,0);proof();return;
    }
    failed(0xa07u,0);
#endif
}

/* No producer can run while this private-stack job holds IRQ/FIQ masked.
 * Defer while any DMA is active; after claim, every path holds until AP reset. */
void terminal_dispatch(const uint32_t *frame) {
    if(M[0]!=TERM_MAGIC || !M[1] || M[2])return;
    M[5]++;M[20]=frame[2];M[14]=frame[0];
    uint32_t sp;
    __asm__ volatile("mov %0,sp":"=r"(sp));M[13]=sp;
    publish(T_WAIT,0,0x500a0024u);
    /* A foreground CP_CALL can arrive while LPS has gated the DMA/PHY bus.
       Cached RF fields or an idle allocator do not make MMIO readable. The
       always-on power status must pass before even the first DMA read. */
    uint32_t zsp_power=R32(0x500a0024u),phy_power=R32(0x500a0028u);
    if(M[7] && (zsp_power!=3u || phy_power!=3u)) {
        /* Single-shot foreground wake. Check software owners and the fixed
           RF input before changing power. After claiming, no path returns
           to the vendor tasks, even when wake or a later DMA gate fails. */
        if((R32(RXCAPT_DMA_ALLOCATOR_ADDRESS)&0x03800380u) ||
           R16(RXCAPT_CAPTURE_BITMAP_ADDRESS) || (R32(0x804689a4u)&0xeu) || R16(0x8048df56u)) {
            retry_profile_or_expire(0x920u,0x804689a4u,R32(0x804689a4u));return;
        }
        if(!terminal_bandwidth_valid(CFG[4])) {
            retry_profile_or_expire(0x951u,TERM_CONFIG+16u,CFG[4]);return;
        }
#if defined(RXCAPT_RAW_FREQUENCY_SWEEP) && RXCAPT_RAW_FREQUENCY_SWEEP
        if(
#if defined(RXCAPT_MULTI_PROFILE) && RXCAPT_MULTI_PROFILE
           !terminal_profile_raw_valid(CFG[3],CFG[9])
#else
           !terminal_raw_frequency_valid(CFG[9],terminal_profile_anchor(CFG[3]))
#endif
        ) {
            retry_profile_or_expire(0x952u,TERM_CONFIG+36u,CFG[9]);return;
        }
#endif
        M[2]=1;M[1]=0;publish(T_CLAIMED,0,0x500a0024u);
        uint32_t wake_result=terminal_open_domains();
        if(wake_result!=1u)failed(wake_result,1);
        zsp_power=R32(0x500a0024u);phy_power=R32(0x500a0028u);
    }
    if(zsp_power!=3u || phy_power!=3u) {
        M[27]=phy_power;
        retry_profile_or_expire(0x950u,0x500a0024u,zsp_power);return;
    }
    for(unsigned ch=0;ch<12;ch++) {
        uint32_t base=dma_channel_base(ch);
        if(!base)failed(0x90fu+ch,1);
        publish(T_WAIT,0,base);
        uint32_t control=R32(base),sgconf=R32(base+0x18u);
        if((control&1u) || (sgconf&1u)) {
            if(M[2]){snapshot_preclaim_dma_wait(base,control,sgconf);failed(0x910u+ch,1);}
            if(M[5]>=320u || M[7]){
                snapshot_preclaim_dma_wait(base,control,sgconf);
                M[1]=0;publish(T_WAIT_EXPIRED,0x910u+ch,base);proof();
            }
            else publish(T_WAIT,0x910u+ch,base);
            return;
        }
    }
    if(((R32(RXCAPT_DMA_ALLOCATOR_ADDRESS)&0x03800380u)!=0) ||
       R16(RXCAPT_CAPTURE_BITMAP_ADDRESS) || (R32(0x804689a4u)&0xeu) || R16(0x8048df56u)) {
        if(M[2])failed(0x920u,1);
        if(M[5]>=320u || M[7]){M[1]=0;publish(T_WAIT_EXPIRED,0x920u,0);proof();}
        else publish(T_WAIT,0x920u,0);
        return;
    }
    /* The L1 context can be incomplete during early FCP callbacks. Retry
       until a complete profile for the configured channel is live. Validate
       and retain it before RF-off, which may invalidate the fields. */
    if(M[7]) {
        /* The isolated RF initializer and explicit RX request establish the
           service profile. Do not wait for L1 to create an RX_INFO instance. */
        if(!terminal_bandwidth_valid(CFG[4])) {
            retry_profile_or_expire(0x951u,TERM_CONFIG+16u,CFG[4]);return;
        }
        M[23]=CFG[4];
    } else {
    uint32_t rx_bandwidth=ready_rx_bandwidth();
    M[23]=rx_bandwidth;
    if(rx_bandwidth==0xffffffffu) {
        volatile uint32_t *p=(volatile uint32_t *)RXCAPT_FINITE_PROGRESS_ADDRESS;
        uint32_t address=p[4],detail=p[5];
        retry_profile_or_expire(0x930u,address,detail);return;
    }
    if(rx_bandwidth!=CFG[4]) {
        retry_profile_or_expire(0x931u,0x804ed5acu+0x24u,rx_bandwidth);return;
    }
    uint32_t band=R16(0x804ed5acu);
    if(band!=TERM_EXPECTED_BAND_RAW) {
        retry_profile_or_expire(0x932u,0x804ed5acu,band);return;
    }
    uint32_t frequency=R32(0x804ed5acu+0x1cu);
    if(frequency!=TERM_EXPECTED_FREQUENCY_RAW) {
        retry_profile_or_expire(0x933u,0x804ed5acu+0x1cu,frequency);return;
    }
    }
    /* Do not transition power domains until every DMA and RXCAPT owner is
       confirmed idle. IRQ/FIQ are masked by the native trampoline, so the
       preflight and claim remain one uninterrupted CP-side operation. */
    if(M[7] && !M[2]){M[2]=1;M[1]=0;publish(T_CLAIMED,0,0x500a0024u);}
    uint32_t opened=terminal_open_domains();
    if(opened!=1){M[2]=1;failed(opened,1);}
    /* Read-only baseline after the domains are confirmed open, before the
       forced RF-off and native RF-init chain. Compare with M[25..27] if
       PREPARE later rejects the RXCAPT controls with 0x406. */
    M[28]=R32(0x27000000u);
    M[29]=R32(0x27000004u);
    M[30]=R32(0x27000010u);
    snapshot_rxcapt_registers(0);
    uint32_t rxcap_enable=R32(0x27000000u);
    uint32_t capture_config=R32(0x27000004u);
    uint32_t dma_requests=R32(0x27000010u);
    if((rxcap_enable&1u) || (capture_config&1u) || dma_requests) {
        M[25]=0x27000000u;M[26]=rxcap_enable;M[27]=dma_requests;
        if(M[2]){snapshot_rxcapt_registers(16);failed(0x940u,1);}
        if(M[5]>=320u || M[7]) {
            snapshot_rxcapt_registers(16);
            M[1]=0;publish(T_WAIT_EXPIRED,0x940u,0x27000000u);proof();
        } else publish(T_WAIT,0x940u,0x27000000u);
        return;
    }
    M[2]=1;M[1]=0;publish(T_CLAIMED,0,0);
#if defined(RXCAPT_CONTINUOUS_STREAM) && RXCAPT_CONTINUOUS_STREAM
    if(M[7]!=2u)failed(0xa0bu,1u);
    M[32]=1u;
    M[23]=CFG[4];
#if defined(RXCAPT_REUSABLE_STREAM) && RXCAPT_REUSABLE_STREAM
    M[35]=0u;
    for(;;) {
        transaction(); /* Returns only after drained REARM has been accepted. */
        ++M[32];
        for(unsigned i=0;i<107;i++)((volatile uint32_t *)STATE)[i]=0u;
        M[6]=0u;M[8]=0u;M[9]=0u;M[10]=0u;M[11]=0u;
        M[23]=CFG[4];publish(T_CLAIMED,0,0);
    }
#else
    transaction();
    failed(0xa0cu,1u);
#endif
#else
    uint32_t completed=0;
    for(;;) {
        M[32]=completed+1u;
        M[23]=CFG[4];
        transaction();
        terminal_service_next(++completed);
        /* No modem producer has run since claim. Only a successful fully
           stopped burst reaches here; errors remain pinned until reset. */
        for(unsigned i=0;i<107;i++)((volatile uint32_t *)STATE)[i]=0;
        M[6]=0;M[8]=0;M[9]=0;M[10]=0;M[11]=0;
        publish(T_CLAIMED,0,0);
    }
#endif
}
