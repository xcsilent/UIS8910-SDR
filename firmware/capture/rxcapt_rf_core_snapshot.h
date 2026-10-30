#ifndef RXCAPT_RF_CORE_SNAPSHOT_H
#define RXCAPT_RF_CORE_SNAPSHOT_H
#if defined(RXCAPT_RF_CORE_SNAPSHOT) && RXCAPT_RF_CORE_SNAPSHOT
#define RF_CORE_SNAPSHOT ((volatile uint32_t *)0x8096e400u)
#define RF_CORE_SNAPSHOT_BYTES 512u
#define RF_PRE_RXON_SNAPSHOT ((volatile uint32_t *)0x8096e800u)
#define RF_CORE_SNAPSHOT_FIRST_WINDOW 64u
#define RF_CORE_SNAPSHOT_FACTOR_WINDOW 81u
#define RF_CORE_SNAPSHOT_WINDOW_RADIUS 8u
#if defined(RXCAPT_RF_RX_INPUT_CONTEXT) && RXCAPT_RF_RX_INPUT_CONTEXT
#define RF_RX_INPUT_SNAPSHOT ((volatile uint32_t *)0x8096e600u)
#define RF_RX_INPUT_SNAPSHOT_BYTES 128u
#define RF_RX_INPUT_CONTEXT_MAGIC 0x52564931u
static void terminal_rf_rx_input_snapshot_begin(void) {
    for(unsigned i=0;i<RF_RX_INPUT_SNAPSHOT_BYTES/4u;i++)RF_RX_INPUT_SNAPSHOT[i]=0;
    RF_RX_INPUT_SNAPSHOT[0]=RF_RX_INPUT_CONTEXT_MAGIC;
    RF_RX_INPUT_SNAPSHOT[1]=1u;
    RF_RX_INPUT_SNAPSHOT[2]=TERM_GENERATION;
    clean_range((uint32_t)RF_RX_INPUT_SNAPSHOT,RF_RX_INPUT_SNAPSHOT_BYTES);
}
static void terminal_rf_rx_input_snapshot_capture(uint32_t before_rx,
    uint32_t data_count,uint32_t head_count) {
    volatile uint32_t *out=RF_RX_INPUT_SNAPSHOT;
    if(out[0]!=RF_RX_INPUT_CONTEXT_MAGIC) {
        for(unsigned i=0;i<RF_RX_INPUT_SNAPSHOT_BYTES/4u;i++)out[i]=0u;
        out[0]=RF_RX_INPUT_CONTEXT_MAGIC;out[1]=1u;out[2]=TERM_GENERATION;
    }
    unsigned status=before_rx?3u:8u;
    unsigned first=before_rx?4u:9u;
    if(out[status])return;
    out[status]=1u;
    out[first+0u]=*(volatile uint16_t *)0x50030008u;
    out[first+1u]=*(volatile uint16_t *)0x50030050u;
    out[first+2u]=*(volatile uint16_t *)0x50030054u;
    out[first+3u]=*(volatile uint16_t *)0x50030058u;
    if(!before_rx){out[13]=data_count;out[14]=head_count;}
    out[status]=2u;
    clean_range((uint32_t)out,RF_RX_INPUT_SNAPSHOT_BYTES);
}
#endif
static void terminal_rf_core_snapshot_begin(void) {
    for(unsigned i=0;i<RF_CORE_SNAPSHOT_BYTES/4u;i++)RF_CORE_SNAPSHOT[i]=0;
    clean_range((uint32_t)RF_CORE_SNAPSHOT,RF_CORE_SNAPSHOT_BYTES);
#if defined(RXCAPT_RF_TIMER_SNAPSHOT) && RXCAPT_RF_TIMER_SNAPSHOT
    for(unsigned i=0;i<16u;i++)((volatile uint32_t *)0x8096e600u)[i]=0;
    clean_range(0x8096e600u,64u);
#endif
}
static void terminal_rf_pre_rxon_snapshot_begin(void) {
    for(unsigned i=0;i<RF_CORE_SNAPSHOT_BYTES/4u;i++)RF_PRE_RXON_SNAPSHOT[i]=0;
    clean_range((uint32_t)RF_PRE_RXON_SNAPSHOT,RF_CORE_SNAPSHOT_BYTES);
#if defined(RXCAPT_RF_RX_INPUT_CONTEXT) && RXCAPT_RF_RX_INPUT_CONTEXT
    terminal_rf_rx_input_snapshot_begin();
#endif
}
static __attribute__((noinline,noclone)) void terminal_rf_core_snapshot_to(
    volatile uint32_t *out,uint32_t data_count,uint32_t head_count,uint32_t read_sfr) {
    if(out[0])return;
    (void)read_sfr;
    out[1]=2u;out[2]=TERM_GENERATION;out[3]=1u;
    out[4]=CFG[9]?CFG[9]:terminal_profile_anchor(CFG[3]);
    out[5]=data_count;out[52]=head_count;
    out[6]=R32(0x50007e10u);out[7]=R32(0x50007e14u);
    /* This is the exact shared-status handshake used by the CP consumer.
     * Do not follow an unknown pointer or infer an RF register bus mapping. */
    if(out[6]==0xaaaaaaaau && out[7]==0xb468u) {
        for(unsigned i=0;i<13u;i++)out[8u+i]=R32(0x5000b520u+i*4u);
        for(unsigned i=0;i<31u;i++)out[21u+i]=R32(0x5000b468u+i*4u);
        /* RV frequency calculator 0x37f0: preserve the live factor lookup inputs.
         * The generic monitor intentionally does not expose the 0x50000000 bus. */
        out[53]=*(volatile uint16_t *)0x5000a710u;
        out[54]=*(volatile uint16_t *)0x5000b538u;
        out[55]=0xffffffffu;
        out[56]=0xffffffffu;
        out[57]=0xffffffffu; /* Reserved historical ABI field; branch decoded offline. */
        out[58]=0xffffffffu;out[59]=0u;
        out[60]=0xffffffffu;out[61]=0u;
        out[62]=RF_CORE_SNAPSHOT_FIRST_WINDOW;
        out[63]=RF_CORE_SNAPSHOT_FACTOR_WINDOW;
        if(out[54]<506u) {
            out[55]=*(volatile uint16_t *)(0x5000940cu+out[54]*2u);
            unsigned first_start=out[54]>RF_CORE_SNAPSHOT_WINDOW_RADIUS?
                out[54]-RF_CORE_SNAPSHOT_WINDOW_RADIUS:0u;
            unsigned first_count=506u-first_start;
            if(first_count>17u)first_count=17u;
            out[58]=first_start;out[59]=first_count;
            for(unsigned i=0;i<first_count;i++) {
                unsigned index=first_start+i;
                out[RF_CORE_SNAPSHOT_FIRST_WINDOW+i]=
                    *(volatile uint16_t *)(0x5000940cu+index*2u);
            }
            if(out[55]<1024u) {
                out[56]=*(volatile uint16_t *)(0x5000a714u+out[55]*2u);
                unsigned factor_start=out[55]>RF_CORE_SNAPSHOT_WINDOW_RADIUS?
                    out[55]-RF_CORE_SNAPSHOT_WINDOW_RADIUS:0u;
                unsigned factor_count=1024u-factor_start;
                if(factor_count>17u)factor_count=17u;
                out[60]=factor_start;out[61]=factor_count;
                for(unsigned i=0;i<factor_count;i++) {
                    unsigned index=factor_start+i;
                    out[RF_CORE_SNAPSHOT_FACTOR_WINDOW+i]=
                        *(volatile uint16_t *)(0x5000a714u+index*2u);
                }
            }
        }
#if defined(RXCAPT_RF_CALIBRATION_SNAPSHOT) && RXCAPT_RF_CALIBRATION_SNAPSHOT
        /* RV 0x453c consumes one 15-slot calibration row, not the whole table.
         * Read only shared RAM under the same ownership/handshake as above. */
        out[98]=0x43414c31u;out[99]=1u;
        out[100]=*(volatile uint16_t *)0x5000b464u;
        out[101]=out[54];
        out[102]=out[17]&0xffffu;out[103]=out[17]>>16;
        if(out[101]<=20u && out[102]<15u) {
            unsigned index=15u*out[101]+out[102];
            out[104]=index;
            out[105]=*(volatile uint16_t *)(0x50008764u+2u*index);
            out[106]=*(volatile uint16_t *)(0x50009438u+2u*index);
            out[107]=*(volatile uint16_t *)(0x5000af78u+4u*index);
            out[108]=*(volatile uint16_t *)(0x5000af7au+4u*index);
            out[99]=2u;
        }
#if defined(RXCAPT_RF_SFR_SNAPSHOT) && RXCAPT_RF_SFR_SNAPSHOT
        /* A bounded live test of selected CP/RF address correspondences.
         * No writes, no timer access and no whole-window scan. */
        if(read_sfr) {
        out[109]=0x53465231u;out[110]=1u;
        if(out[99]==2u) {
            unsigned group_b=out[101]<=12u || out[101]==17u;
            uint32_t q8=group_b?0x50030360u:0x50030370u;
            uint32_t low=group_b?0x500302c4u:0x50032228u;
            uint32_t high=group_b?0x500302c8u:0x5003222cu;
            out[111]=group_b?2u:1u;
            out[112]=*(volatile uint16_t *)q8;
            out[113]=*(volatile uint16_t *)low;
            out[114]=*(volatile uint16_t *)high;
            out[115]=*(volatile uint16_t *)(group_b?0x50030364u:0x50030374u);
            out[116]=group_b?0xffffffffu:*(volatile uint16_t *)0x5003037cu;
            out[117]=*(volatile uint16_t *)0x50030448u;
            out[118]=*(volatile uint16_t *)0x50030474u;
            out[119]=*(volatile uint16_t *)0x5003200cu;
            out[120]=*(volatile uint16_t *)0x50032010u;
            out[121]=R32(0x50032004u);
            out[122]=*(volatile uint16_t *)0x50030410u;
            out[123]=*(volatile uint16_t *)(group_b?0x500302c0u:0x500302e0u);
            out[124]=*(volatile uint16_t *)(group_b?0x500302ccu:0x500302e4u);
            out[125]=*(volatile uint16_t *)q8;
            out[126]=*(volatile uint16_t *)low;
            out[127]=*(volatile uint16_t *)high;
            out[110]=2u;
        }
#if defined(RXCAPT_RF_TIMER_SNAPSHOT) && RXCAPT_RF_TIMER_SNAPSHOT
        if(out[110]==2u) {
            volatile uint32_t *timer=(volatile uint32_t *)0x8096e600u;
            timer[0]=0x544d5231u;timer[1]=1u;timer[2]=TERM_GENERATION;timer[3]=1u;
            timer[14]=data_count;timer[15]=head_count;
            timer[4]=R32(0x50090088u);
            clean_range(0x8096e600u,64u);
            /* Experimental CP alias of the RF-local timer. Read only after
             * native RF setup; never arm it or clear its completion state. */
            for(unsigned i=0;i<4u;i++)timer[5u+i]=R32(0x50038000u+4u*i);
            timer[3]=2u;clean_range(0x8096e600u,64u);
            for(unsigned i=0;i<4u;i++)timer[9u+i]=R32(0x50038000u+4u*i);
            timer[13]=R32(0x50090088u);
            timer[3]=3u;clean_range(0x8096e600u,64u);
        }
#endif
        }
#endif
#endif
#if defined(RXCAPT_RF_CROSS_CORE_WIDTH_SNAPSHOT) && RXCAPT_RF_CROSS_CORE_WIDTH_SNAPSHOT
        /* Compare software-width views without writing the RF window. Keep the
         * legacy v2 snapshot layout except for three documented spare words:
         * 57=0x50032004 halfword, 62/63=the four 0x500303xx halfwords. Word
         * 121 retains the 0x50032004 word read when SFR capture is enabled. */
        if(out[99]==2u) {
            if(!read_sfr)out[121]=R32(0x50032004u);
            out[57]=*(volatile uint16_t *)0x50032004u;
            out[62]=(uint32_t)*(volatile uint16_t *)0x5003030cu |
                    ((uint32_t)*(volatile uint16_t *)0x50030310u<<16);
            out[63]=(uint32_t)*(volatile uint16_t *)0x5003033cu |
                    ((uint32_t)*(volatile uint16_t *)0x50030340u<<16);
            out[1]=3u;
        }
#endif
#if defined(RXCAPT_RF_RX_INPUT_CONTEXT) && RXCAPT_RF_RX_INPUT_CONTEXT
        terminal_rf_rx_input_snapshot_capture(out==RF_PRE_RXON_SNAPSHOT,
            data_count,head_count);
#endif
        out[3]=2u;
    }
    out[0]=0x52465331u;
    clean_range((uint32_t)out,RF_CORE_SNAPSHOT_BYTES);
}
static __attribute__((noinline,noclone)) void terminal_rf_core_snapshot(
    uint32_t data_count,uint32_t head_count) {
    terminal_rf_core_snapshot_to(RF_CORE_SNAPSHOT,data_count,head_count,1u);
}
static __attribute__((noinline,noclone)) void terminal_rf_core_snapshot_pre_rxon(void) {
    terminal_rf_core_snapshot_to(RF_PRE_RXON_SNAPSHOT,0u,0u,0u);
}
#else
#define terminal_rf_core_snapshot_begin() ((void)0)
#define terminal_rf_core_snapshot(data_count,head_count) ((void)0)
#define terminal_rf_pre_rxon_snapshot_begin() ((void)0)
#define terminal_rf_core_snapshot_pre_rxon() ((void)0)
#endif
#endif
