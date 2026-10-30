#ifndef RXCAPT_RF_COEFFICIENT_PROBE_H
#define RXCAPT_RF_COEFFICIENT_PROBE_H
#if defined(RXCAPT_RF_COEFFICIENT_PROBE) && RXCAPT_RF_COEFFICIENT_PROBE
#define RF_COEFFICIENT_PROBE ((volatile uint32_t *)0x8096e640u)

static void terminal_rf_coefficient_probe_begin(void) {
    for(unsigned i=0;i<64u;i++)RF_COEFFICIENT_PROBE[i]=0;
    clean_range(0x8096e640u,256u);
}

static void coefficient_probe_finish(uint32_t phase,uint32_t result) {
    RF_COEFFICIENT_PROBE[4]=result;
    RF_COEFFICIENT_PROBE[3]=phase;
    clean_range(0x8096e640u,256u);
}

/* One bounded experiment while the CP private job still owns RF. Never accepts
 * saved host values, changes a frequency, or resumes vendor tasks. */
static __attribute__((noinline,noclone)) void terminal_rf_coefficient_probe(void) {
    static const uint32_t addresses[3]={0x50030370u,0x50032228u,0x5003222cu};
    volatile uint32_t *out=RF_COEFFICIENT_PROBE;
    volatile uint32_t *snapshot=(volatile uint32_t *)0x8096e400u;
    if(out[0])return;
#if defined(RXCAPT_RF_COEFFICIENT_DELTA_PROBE) && RXCAPT_RF_COEFFICIENT_DELTA_PROBE
    out[0]=0x32504643u; /* CFP2: changed-value write/restore */
#else
    out[0]=0x31504643u; /* CFP1 */
#endif
    out[1]=1u;out[2]=TERM_GENERATION;out[3]=1u;
    __asm__ volatile("mrs %0,cpsr":"=r"(out[5]));
    out[6]=M[3];out[7]=STATE->phase;out[8]=M[2];
    out[9]=STATE->data_channel;out[10]=STATE->head_channel;
    if((out[5]&0xc0u)!=0xc0u || M[0]!=TERM_MAGIC || !out[8] ||
       out[6]!=T_HELD || out[7]!=RXCAPT_PHASE_HELD || STREAM[8]!=STREAM_REASON_HOST ||
       out[9]<7u || out[9]>9u || out[10]<7u || out[10]>9u || out[9]==out[10]) {
        coefficient_probe_finish(5u,2u);return;
    }
    out[11]=R32(0x500a0024u);out[12]=R32(0x500a0028u);
    if(out[11]!=3u || out[12]!=3u) {coefficient_probe_finish(5u,3u);return;}
    uint32_t data=dma_channel_base(out[9]),head=dma_channel_base(out[10]);
    if(!data || !head || data==head) {coefficient_probe_finish(5u,4u);return;}
    out[13]=R32(data);out[14]=R32(data+0x18u);
    out[15]=R32(head);out[16]=R32(head+0x18u);
    if((out[13]|out[14]|out[15]|out[16])&1u) {coefficient_probe_finish(5u,4u);return;}
    if(snapshot[0]!=0x52465331u || snapshot[2]!=TERM_GENERATION || snapshot[3]!=2u ||
       snapshot[98]!=0x43414c31u || snapshot[99]!=2u || snapshot[101]!=15u ||
       snapshot[109]!=0x53465231u || snapshot[110]!=2u || snapshot[111]!=1u) {
        coefficient_probe_finish(5u,5u);return;
    }
    out[17]=R32(0x50007e10u);out[18]=R32(0x50007e14u);
    if(out[17]!=0xaaaaaaaau || out[18]!=0xb468u) {coefficient_probe_finish(5u,5u);return;}
    out[19]=R16(0x5000b538u);
    if(out[19]!=15u) {coefficient_probe_finish(5u,5u);return;}
    for(unsigned i=0;i<3u;i++)out[20u+i]=R16(addresses[i]);
    __asm__ volatile("dsb sy":::"memory");
    for(unsigned i=0;i<3u;i++)out[23u+i]=R16(addresses[i]);
    for(unsigned i=0;i<3u;i++) {
        out[36u+i]=snapshot[112u+i];
        if(out[20u+i]!=out[23u+i]) {coefficient_probe_finish(5u,6u);return;}
        if(out[20u+i]!=out[36u+i]) {coefficient_probe_finish(5u,7u);return;}
    }
    out[3]=2u;clean_range(0x8096e640u,256u);
#if defined(RXCAPT_RF_COEFFICIENT_DELTA_PROBE) && RXCAPT_RF_COEFFICIENT_DELTA_PROBE
    /* A one-bit delta distinguishes an accepted write from an ignored
     * same-value write. Each value is restored and checked before proceeding
     * to the next address; the probe runs only after RF and DMA are stopped. */
    for(unsigned i=0;i<3u;i++) {
        uint16_t original=(uint16_t)out[20u+i];
        R16(addresses[i])=(uint16_t)(original^1u);
        __asm__ volatile("dsb sy":::"memory");
        out[29]=i+1u;
        out[23u+i]=R16(addresses[i]);
        R16(addresses[i])=original;
        __asm__ volatile("dsb sy":::"memory");
        out[31]=i+1u;
        out[26u+i]=R16(addresses[i]);
        if(out[23u+i]!=(uint32_t)(original^1u)) {
            out[30]=i+1u;coefficient_probe_finish(4u,8u);return;
        }
        if(out[26u+i]!=original) {
            out[30]=i+1u;coefficient_probe_finish(4u,9u);return;
        }
    }
    for(unsigned i=0;i<3u;i++) {
        out[32u+i]=R16(addresses[i]);
        if(out[32u+i]!=out[20u+i]) {
            out[30]=i+1u;coefficient_probe_finish(4u,9u);return;
        }
    }
    coefficient_probe_finish(3u,1u);
#else
    for(unsigned i=0;i<3u;i++) {
        R16(addresses[i])=(uint16_t)out[20u+i];
        __asm__ volatile("dsb sy":::"memory");
        out[29]=i+1u;
        out[26u+i]=R16(addresses[i]);
        if(out[26u+i]!=out[20u+i]) {
            out[30]=i+1u;coefficient_probe_finish(4u,8u);return;
        }
    }
    for(unsigned i=0;i<3u;i++) {
        out[32u+i]=R16(addresses[i]);
        if(out[32u+i]!=out[20u+i]) {
            out[30]=i+1u;coefficient_probe_finish(4u,8u);return;
        }
    }
    coefficient_probe_finish(3u,1u);
#endif
}
#endif
#endif
