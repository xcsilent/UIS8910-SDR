#ifndef RXCAPT_RF_FIXED_CONFIG_PROBE_H
#define RXCAPT_RF_FIXED_CONFIG_PROBE_H
#if defined(RXCAPT_RF_FIXED_CONFIG_PROBE) && RXCAPT_RF_FIXED_CONFIG_PROBE
#if !defined(RXCAPT_RF_TARGET_REGISTER_SNAPSHOT) || !RXCAPT_RF_TARGET_REGISTER_SNAPSHOT
#error fixed config probe requires the post-teardown target snapshot
#endif
#define RF_FIXED_CONFIG_PROBE ((volatile uint32_t *)0x8096eb00u)
#if defined(RXCAPT_RF_INPUT_FIELD_PROBE) && RXCAPT_RF_INPUT_FIELD_PROBE
#define RF_FIXED_CONFIG_PROBE_MAGIC 0x33434650u
#elif defined(RXCAPT_RF_FIXED_CONFIG_DELTA_PROBE) && RXCAPT_RF_FIXED_CONFIG_DELTA_PROBE
#define RF_FIXED_CONFIG_PROBE_MAGIC 0x32434650u
#else
#define RF_FIXED_CONFIG_PROBE_MAGIC 0x31434650u
#endif

static void terminal_rf_fixed_config_probe_begin(void) {
    volatile uint32_t *out=RF_FIXED_CONFIG_PROBE;
    for(unsigned i=0;i<64u;i++)out[i]=0u;
    out[0]=RF_FIXED_CONFIG_PROBE_MAGIC;out[1]=1u;out[2]=TERM_GENERATION;
    clean_range((uint32_t)out,256u);
}

static void fixed_config_probe_finish(uint32_t phase,uint32_t result) {
    RF_FIXED_CONFIG_PROBE[4]=result;RF_FIXED_CONFIG_PROBE[3]=phase;
    clean_range((uint32_t)RF_FIXED_CONFIG_PROBE,256u);
}

/* Re-check the live ownership/idle/context gates around each write. */
static uint32_t fixed_config_probe_guard(void) {
    volatile uint32_t *out=RF_FIXED_CONFIG_PROBE;
    uint32_t cpsr;
    out[26]++;
    __asm__ volatile("mrs %0,cpsr":"=r"(cpsr));
    out[5]=cpsr;out[6]=M[3];out[7]=STATE->phase;out[8]=M[2];out[9]=STREAM[8];
    out[10]=STATE->data_channel;out[11]=STATE->head_channel;
    if((cpsr&0xc0u)!=0xc0u || M[0]!=TERM_MAGIC || !out[8] ||
       out[6]!=T_HELD || out[7]!=RXCAPT_PHASE_HELD ||
       (out[9]!=STREAM_REASON_HOST && out[9]!=STREAM_REASON_FULL) ||
       out[10]<7u || out[10]>9u || out[11]<7u || out[11]>9u || out[10]==out[11])return 2u;
    out[12]=R32(0x500a0024u);out[13]=R32(0x500a0028u);
    if(out[12]!=3u || out[13]!=3u)return 3u;
    uint32_t data=dma_channel_base(out[10]),head=dma_channel_base(out[11]);
    if(!data || !head || data==head)return 4u;
    out[14]=R32(data);out[15]=R32(data+0x18u);
    out[16]=R32(head);out[17]=R32(head+0x18u);
    if((out[14]|out[15]|out[16]|out[17])&1u)return 4u;
    out[18]=R32(0x50007e10u);out[19]=R32(0x50007e14u);
    if(out[18]!=0xaaaaaaaau || out[19]!=0xb468u)return 5u;
    out[20]=R16(0x5000b530u);out[21]=R16(0x5000b538u);
    if(out[20]!=5u || out[21]!=15u)return 5u;
#if defined(RXCAPT_RF_INPUT_FIELD_PROBE) && RXCAPT_RF_INPUT_FIELD_PROBE
    out[60]=R16(0x5000b546u);
    out[61]=((volatile uint32_t *)0x8096e400u)[103];
    if(out[60]>0xfffu || out[60]!=out[61])return 5u;
    if(out[3]>=2u && out[60]!=out[55])return 5u;
#endif
    return 0u;
}

static void fixed_config_probe_restore(unsigned index,uint32_t address) {
    volatile uint32_t *out=RF_FIXED_CONFIG_PROBE;
    out[27]=fixed_config_probe_guard();
    if(out[27])return;
    R16(address)=(uint16_t)out[28u+index];
    __asm__ volatile("dsb sy":::"memory");
    out[24]++;
    out[48u+index]=R16(address);
    if(out[48u+index]!=out[28u+index])out[25]|=1u<<index;
}

/* One bounded configuration experiment, restricted to the selected addresses.
 * Never consumes a saved host value, changes the requested raw or resumes tasks. */
static __attribute__((noinline,noclone)) void terminal_rf_fixed_config_probe(void) {
#if defined(RXCAPT_RF_INPUT_FIELD_PROBE) && RXCAPT_RF_INPUT_FIELD_PROBE
    static const uint32_t addresses[4]={0x50032020u,0x50032008u,0x5003201cu,0x50032128u};
    static const uint32_t indices[4]={24u,22u,23u,25u};
    uint16_t mode5_values[4]={0u,1u,0x0a02u,0x1000u};
#else
    static const uint32_t addresses[4]={0x5003044cu,0x50032008u,0x5003201cu,0x50032128u};
    static const uint32_t indices[4]={19u,22u,23u,25u};
    static const uint16_t mode5_values[4]={0xad34u,1u,0x0a02u,0x1000u};
#endif
    volatile uint32_t *out=RF_FIXED_CONFIG_PROBE;
    volatile uint32_t *target=RF_TARGET_REGISTER_SNAPSHOT;
    volatile uint32_t *core=(volatile uint32_t *)0x8096e400u;
    if(out[0]!=RF_FIXED_CONFIG_PROBE_MAGIC || out[1]!=1u || out[2]!=TERM_GENERATION || out[3])return;
    out[3]=1u;
    out[27]=fixed_config_probe_guard();
    if(out[27]) {fixed_config_probe_finish(5u,out[27]);return;}
    if(target[0]!=RF_TARGET_REGISTER_SNAPSHOT_MAGIC || target[1]!=1u ||
       target[2]!=TERM_GENERATION || target[3]!=2u || target[4]!=T_HELD ||
       target[5]!=RXCAPT_PHASE_HELD || target[6]!=out[9] || !target[7] ||
       target[8]!=out[10] || target[9]!=out[11] ||
       core[0]!=0x52465331u || core[2]!=TERM_GENERATION || core[3]!=2u ||
       (core[12]&0xffffu)!=5u || (core[14]&0xffffu)!=15u ||
       core[98]!=0x43414c31u || core[99]!=2u || core[101]!=15u) {
        fixed_config_probe_finish(5u,6u);return;
    }
#if defined(RXCAPT_RF_INPUT_FIELD_PROBE) && RXCAPT_RF_INPUT_FIELD_PROBE
    out[55]=out[60];mode5_values[0]=(uint16_t)(out[55]|0x1000u);
#endif
    for(unsigned i=0;i<4u;i++) {
        out[56u+i]=addresses[i];out[44u+i]=target[indices[i]];
        out[28u+i]=R16(addresses[i]);
    }
    __asm__ volatile("dsb sy":::"memory");
    for(unsigned i=0;i<4u;i++)out[32u+i]=R16(addresses[i]);
    for(unsigned i=0;i<4u;i++) {
        if(out[28u+i]!=out[32u+i]) {fixed_config_probe_finish(5u,7u);return;}
        if(out[28u+i]!=out[44u+i] || out[28u+i]!=mode5_values[i]) {
            fixed_config_probe_finish(5u,8u);return;
        }
    }
    out[3]=2u;clean_range((uint32_t)out,256u);
#if (defined(RXCAPT_RF_FIXED_CONFIG_DELTA_PROBE) && RXCAPT_RF_FIXED_CONFIG_DELTA_PROBE) || \
    (defined(RXCAPT_RF_INPUT_FIELD_PROBE) && RXCAPT_RF_INPUT_FIELD_PROBE)
    /* Only 0x3044c changes. Original RV mode-6 store at 0x4578 emits 0x9534;
     * the current mode-5 value (0xad34) was freshly captured above. This does
     * not switch the software mode or execute any receive/tune sequence. */
#if defined(RXCAPT_RF_INPUT_FIELD_PROBE) && RXCAPT_RF_INPUT_FIELD_PROBE
    /* RV 0x459c stores context16 | 0x1000. Both alternate fields have
     * captured mode-5 provenance. Never update the live context itself. */
    out[62]=(out[55]==0x79u)?0x49u:0x79u;
    out[52]=0u;out[53]=out[62]|0x1000u;out[54]=0x459cu;
#else
    out[52]=0u;out[53]=0x9534u;out[54]=0x4578u;
#endif
    out[27]=fixed_config_probe_guard();
    if(out[27]) {fixed_config_probe_finish(5u,out[27]);return;}
    if(R16(addresses[0])!=out[28]) {out[23]=1u;fixed_config_probe_finish(5u,8u);return;}
    R16(addresses[0])=(uint16_t)out[53];
    __asm__ volatile("dsb sy":::"memory");
    out[22]=1u;out[36]=R16(addresses[0]);
    out[27]=fixed_config_probe_guard();
    if(out[27]) {fixed_config_probe_finish(4u,out[27]);return;}
    R16(addresses[0])=(uint16_t)out[28];
    __asm__ volatile("dsb sy":::"memory");
    out[24]=1u;out[48]=R16(addresses[0]);
    if(out[48]!=out[28])out[25]=1u;
    out[27]=fixed_config_probe_guard();
    if(out[27]) {fixed_config_probe_finish(4u,out[27]);return;}
    if(out[36]!=out[53]) {out[23]=1u;fixed_config_probe_finish(4u,9u);return;}
    if(out[25]) {out[23]=1u;fixed_config_probe_finish(4u,11u);return;}
    for(unsigned i=0;i<4u;i++) {
        out[40u+i]=R16(addresses[i]);
        if(out[40u+i]!=out[28u+i]) {
            out[23]=i+1u;fixed_config_probe_finish(4u,10u);return;
        }
    }
    out[27]=fixed_config_probe_guard();
    if(out[27]) {fixed_config_probe_finish(4u,out[27]);return;}
    fixed_config_probe_finish(3u,1u);
#else
    for(unsigned i=0;i<4u;i++) {
        out[27]=fixed_config_probe_guard();
        if(out[27]) {fixed_config_probe_finish(out[22]?4u:5u,out[27]);return;}
        if(R16(addresses[i])!=out[28u+i]) {
            out[23]=i+1u;fixed_config_probe_finish(out[22]?4u:5u,8u);return;
        }
        R16(addresses[i])=(uint16_t)out[28u+i];
        __asm__ volatile("dsb sy":::"memory");
        out[22]=i+1u;out[36u+i]=R16(addresses[i]);
        out[27]=fixed_config_probe_guard();
        if(out[27]) {fixed_config_probe_finish(4u,out[27]);return;}
        if(out[36u+i]!=out[28u+i]) {
            out[23]=i+1u;fixed_config_probe_restore(i,addresses[i]);
            fixed_config_probe_finish(4u,9u);return;
        }
    }
    out[27]=fixed_config_probe_guard();
    if(out[27]) {fixed_config_probe_finish(4u,out[27]);return;}
    for(unsigned i=0;i<4u;i++) {
        out[40u+i]=R16(addresses[i]);
        if(out[40u+i]!=out[28u+i]) {
            out[23]=i+1u;fixed_config_probe_restore(i,addresses[i]);
            fixed_config_probe_finish(4u,10u);return;
        }
    }
    out[27]=fixed_config_probe_guard();
    if(out[27]) {fixed_config_probe_finish(4u,out[27]);return;}
    fixed_config_probe_finish(3u,1u);
#endif
}
#endif
#endif
