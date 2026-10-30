#include <stdint.h>
#include "terminal_control_binding.h"
#include "cp_agent_expected.h"
#include "rxcapt_raw_frequency.h"
#include "rxcapt_profile.h"
#define M ((volatile uint32_t *)TERM_META)
#define P ((volatile uint32_t *)TERM_PROGRESS)
#define CFG ((volatile uint32_t *)TERM_CONFIG)

#if defined(RXCAPT_CONTINUOUS_STREAM) && RXCAPT_CONTINUOUS_STREAM
static __attribute__((noinline)) int valid_stream_profile(void) {
    uint32_t channel=CFG[3],raw=CFG[9];
    if(CFG[0] || CFG[1]!=2u || CFG[2]!=1u || !terminal_profile_channel_valid(channel) ||
       CFG[4]>5u || CFG[5]>124u || CFG[6] || CFG[7] ||
       CFG[8]!=30720u)return 0;
#if defined(RXCAPT_USB_MAX_BW)
    if(CFG[4]>RXCAPT_USB_MAX_BW)return 0;
#endif
#if !defined(RXCAPT_ALLOW_ZERO_BANDWIDTH) || !RXCAPT_ALLOW_ZERO_BANDWIDTH
    if(CFG[4]<1u)return 0;
#endif
    uint32_t anchor=terminal_profile_anchor(channel);
#if defined(RXCAPT_MULTI_PROFILE) && RXCAPT_MULTI_PROFILE
    (void)anchor;
    return terminal_profile_raw_valid(channel,raw);
#else
    return terminal_raw_frequency_valid(raw,anchor);
#endif
}
#endif

static int equal(uint32_t a,const unsigned char *expected,unsigned n) {
    for(unsigned i=0;i<n;i++)if(((volatile const unsigned char *)a)[i]!=expected[i])return 0;
    return 1;
}
static int permission(void) {
    uint32_t midr,sctlr,ttbr,ttbcr,dacr;
    __asm__ volatile("mrc p15,0,%0,c0,c0,0\nmrc p15,0,%1,c1,c0,0\n"
                     "mrc p15,0,%2,c2,c0,0\nmrc p15,0,%3,c2,c0,2\nmrc p15,0,%4,c3,c0,0"
                     :"=r"(midr),"=r"(sctlr),"=r"(ttbr),"=r"(ttbcr),"=r"(dacr));
    return midr==0x410fc051u && sctlr==0x00c5187fu && (ttbr&~0x3fffu)==0x80428000u && !ttbcr &&
        dacr==0x55555555u && *(volatile uint32_t *)TERM_L1_ADDRESS==TERM_L1_DESCRIPTOR &&
        *(volatile uint32_t *)TERM_L2_ADDRESS==TERM_L2_DESCRIPTOR &&
        (!TERM_SERVICE_MAILBOX || *(volatile uint32_t *)0x8042a03cu==0x80f089e2u) &&
        equal(0x80971000u,cp_agent_expected,sizeof(cp_agent_expected));
}
static uint32_t crc(void) {
    uint32_t v=0xffffffffu;
    for(unsigned i=0;i<TERM_RESIDENT_BYTES;i++) {
        v^=((volatile const unsigned char *)TERM_RESIDENT)[i];
        for(unsigned bit=0;bit<8;bit++)v=(v>>1)^((0u-(v&1u))&0xedb88320u);
    }
    return ~v;
}
static void sync(uint32_t a,unsigned n) {
    uint32_t z=0;
    for(uint32_t line=a&~31u;line<a+n;line+=32)__asm__ volatile("mcr p15,0,%0,c7,c10,1"::"r"(line):"memory");
    __asm__ volatile("dsb sy\nmcr p15,0,%0,c7,c5,0\ndsb sy\nisb sy"::"r"(z):"memory");
}
#if defined(RXCAPT_CONTINUOUS_STREAM) && RXCAPT_CONTINUOUS_STREAM && defined(RXCAPT_STREAM_EXPORT_ADDRESS)
static __attribute__((noinline,noclone)) void clear_stream_export_mirror(void) {
    for(unsigned i=0;i<30u;i++)((volatile uint32_t *)RXCAPT_STREAM_EXPORT_ADDRESS)[i]=0;
    sync(RXCAPT_STREAM_EXPORT_ADDRESS,120u);
}
#endif
__attribute__((section(".text.entry"))) uint32_t terminal_control(uint32_t command) {
    if(command==0x1000)return TERM_MAGIC;
    uint32_t flags,result=0xfffffffcu;
    __asm__ volatile("mrs %0,cpsr\ncpsid if":"=r"(flags)::"memory");
    if(command==0x1001 && permission() && equal(TERM_TARGET,terminal_expected,sizeof(terminal_expected)) &&
       crc()==TERM_RESIDENT_CRC32) {
        for(unsigned i=0;i<64;i++)M[i]=0;
        for(unsigned i=0;i<TERM_FINITE_STATE_WORDS;i++)((volatile uint32_t *)TERM_FINITE_STATE)[i]=0;
        for(unsigned i=0;i<32;i++)((volatile uint32_t *)TERM_PLAN)[i]=0;
        for(unsigned i=0;i<16;i++)((volatile uint32_t *)TERM_EVENT_OUT)[i]=0;
        for(unsigned i=0;i<16;i++)((volatile uint32_t *)TERM_RX_OUT)[i]=0;
        for(unsigned i=0;i<16;i++)P[i]=0;
        for(unsigned i=0;i<128;i++)((volatile uint32_t *)TERM_PROOF)[i]=0;
        const uint32_t cfg[9]={0,TERM_DEFAULT_MODE,TERM_DEFAULT_BAND_INDICATOR,
            TERM_DEFAULT_CHANNEL,TERM_DEFAULT_BANDWIDTH_INDEX,TERM_DEFAULT_GAIN,
            0,0,TERM_DEFAULT_LENGTH};
        for(unsigned i=0;i<9;i++)((volatile uint32_t *)TERM_CONFIG)[i]=cfg[i];
        ((volatile uint32_t *)TERM_CONFIG)[9]=0;
#if defined(RXCAPT_EXPERIMENTAL_FEM_OVERRIDE) && RXCAPT_EXPERIMENTAL_FEM_OVERRIDE
        ((volatile uint32_t *)TERM_CONFIG)[11]=0u;
#endif
#if defined(RXCAPT_EXPERIMENTAL_PRE_SWITCH) && RXCAPT_EXPERIMENTAL_PRE_SWITCH
        ((volatile uint32_t *)TERM_CONFIG)[10]=5u;
#endif
        for(unsigned i=0;i<16;i++)((volatile uint32_t *)TERM_FREQUENCY_EXPORT)[i]=0;
#if defined(RXCAPT_CONTINUOUS_STREAM) && RXCAPT_CONTINUOUS_STREAM && defined(RXCAPT_STREAM_EXPORT_ADDRESS)
        /* A software reset can preserve the previous run's drained mirror.
         * Clear it before the async producer starts; otherwise the host can
         * mistake old STOP/release counters for the new session and PARK early. */
        clear_stream_export_mirror();
#endif
        M[0]=TERM_MAGIC;M[3]=1;M[12]=TERM_GENERATION;M[24]=2;
        P[0]=TERM_MAGIC;P[1]=TERM_GENERATION;P[2]=2;P[3]=1;
        sync(TERM_RESIDENT,TERM_RESIDENT_BYTES);
        sync(TERM_PROGRESS,64);result=7;
#if !defined(RXCAPT_CONTINUOUS_STREAM) || !RXCAPT_CONTINUOUS_STREAM
    } else if(command==0x1003 && M[0]==TERM_MAGIC && !M[1] && !M[2] && permission() &&
              equal(TERM_TARGET,terminal_expected,sizeof(terminal_expected)) && crc()==TERM_RESIDENT_CRC32) {
        M[1]=1;
        uint32_t manager=0xd5555555u,client=0x55555555u;
        __asm__ volatile("dsb sy\nmcr p15,0,%0,c3,c0,0\nisb sy"::"r"(manager):"memory");
        volatile uint16_t *out=(volatile uint16_t *)TERM_TARGET;
        for(unsigned i=2;i<5;i++)out[i]=(uint16_t)(terminal_branch[2*i]|((uint16_t)terminal_branch[2*i+1]<<8));
        for(unsigned i=0;i<2;i++)out[i]=(uint16_t)(terminal_branch[2*i]|((uint16_t)terminal_branch[2*i+1]<<8));
        sync(TERM_TARGET,10);
        __asm__ volatile("mcr p15,0,%0,c3,c0,0\nisb sy"::"r"(client):"memory");
        result=equal(TERM_TARGET,terminal_branch,10)?7:0xfffffffcu;
#endif
#if defined(RXCAPT_CONTINUOUS_STREAM) && RXCAPT_CONTINUOUS_STREAM
    } else if(command==0x100b && M[0]==TERM_MAGIC && !M[2] && !M[6] &&
              (M[3]==1 || M[3]==10) && valid_stream_profile() && permission() &&
              equal(TERM_TARGET,terminal_expected,sizeof(terminal_expected)) && crc()==TERM_RESIDENT_CRC32) {
        M[7]=2u;
        M[1]=1;
        ((void (*)(void))TERM_FOREGROUND_ENTRY)();
        result=7;
#else
    } else if((command==0x1007 || command==0x1009) && M[0]==TERM_MAGIC && !M[2] && !M[6] &&
              (M[3]==1 || M[3]==10) && permission() &&
              equal(TERM_TARGET,terminal_expected,sizeof(terminal_expected)) && crc()==TERM_RESIDENT_CRC32) {
        M[7]=command==0x1009;
        M[1]=1;
        ((void (*)(void))TERM_FOREGROUND_ENTRY)();
        result=7;
#endif
    } else if(command==0x1005 && M[0]==TERM_MAGIC && !M[2] && !M[6] &&
              (M[3]==1 || M[3]==10 || M[3]==33) && permission() &&
              (equal(TERM_TARGET,terminal_branch,10) ||
               equal(TERM_TARGET,terminal_expected,sizeof(terminal_expected))) && crc()==TERM_RESIDENT_CRC32) {
        if(equal(TERM_TARGET,terminal_expected,sizeof(terminal_expected))) {
            M[1]=0;M[0]=0;result=7;
        } else {
            uint32_t manager=0xd5555555u,client=0x55555555u;
            __asm__ volatile("dsb sy\nmcr p15,0,%0,c3,c0,0\nisb sy"::"r"(manager):"memory");
            volatile uint16_t *out=(volatile uint16_t *)TERM_TARGET;
            for(unsigned i=2;i<5;i++)out[i]=(uint16_t)(terminal_expected[2*i]|((uint16_t)terminal_expected[2*i+1]<<8));
            for(unsigned i=0;i<2;i++)out[i]=(uint16_t)(terminal_expected[2*i]|((uint16_t)terminal_expected[2*i+1]<<8));
            sync(TERM_TARGET,10);
            __asm__ volatile("mcr p15,0,%0,c3,c0,0\nisb sy"::"r"(client):"memory");
            if(equal(TERM_TARGET,terminal_expected,10)) { M[1]=0;M[0]=0;result=7; }
        }
    }
    __asm__ volatile("dsb sy\nmsr cpsr_c,%0"::"r"(flags):"memory");
    return result;
}
