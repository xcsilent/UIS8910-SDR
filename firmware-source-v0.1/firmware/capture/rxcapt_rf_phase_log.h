#ifndef RXCAPT_RF_PHASE_LOG_H
#define RXCAPT_RF_PHASE_LOG_H
#if defined(RXCAPT_RF_PHASE_LOG) && RXCAPT_RF_PHASE_LOG
/* One fixed record per reception boundary. No RF writes or polling. */
#define RF_PHASE_LOG ((volatile uint32_t *)0x8096ec00u)
#define RF_PHASE_LOG_WORDS 296u
#define RF_PHASE_ROW_WORDS 56u
#if defined(RXCAPT_RF_CODE_SNAPSHOT) && RXCAPT_RF_CODE_SNAPSHOT
#define RF_CODE_SNAPSHOT ((volatile uint32_t *)0x8096f100u)
#define RF_CODE_SNAPSHOT_BYTES 1664u
static void terminal_rf_code_snapshot_begin(void) {
    for(unsigned i=0;i<16u;i++)RF_CODE_SNAPSHOT[i]=0u;
    clean_range((uint32_t)RF_CODE_SNAPSHOT,64u);
}
static __attribute__((noinline,noclone)) void terminal_rf_code_snapshot(void) {
    volatile uint32_t *out=RF_CODE_SNAPSHOT;
    if(out[0])return;
    out[1]=1u;out[2]=TERM_GENERATION;out[3]=1u;out[4]=RF_CODE_SNAPSHOT_BYTES;
    out[5]=R32(0x50007e10u);out[6]=R32(0x50007e14u);out[7]=3u;
    out[8]=0x6376u;out[9]=0x66eau-0x6376u;
    out[10]=0x38a8u;out[11]=0x3a7cu-0x38a8u;
#if defined(RXCAPT_RF_RXON_COEFF_STAMP) && RXCAPT_RF_RXON_COEFF_STAMP
    out[1]=2u;out[10]=0x46f6u;out[11]=0x48cau-0x46f6u;
#endif
    out[12]=0x453cu;out[13]=0x4632u-0x453cu;
#if defined(RXCAPT_RF_RXON_REQUEST_STAMP) && RXCAPT_RF_RXON_REQUEST_STAMP
    out[1]=3u;out[12]=0x602cu;out[13]=0x6122u-0x602cu;
#endif
#if defined(RXCAPT_RF_FREQUENCY_STAMP) && RXCAPT_RF_FREQUENCY_STAMP
    out[1]=4u;out[8]=0x37f0u;out[9]=0x38a8u-0x37f0u;
#endif
#if defined(RXCAPT_RF_RXON_PREPARE_STAMP) && RXCAPT_RF_RXON_PREPARE_STAMP
    out[1]=5u;out[11]=0x4a58u-0x46f6u;
#endif
#if defined(RXCAPT_RF_RXON_FINISH_STAMP) && RXCAPT_RF_RXON_FINISH_STAMP
    out[1]=6u;out[8]=0x662cu;out[9]=0x6694u-0x662cu;
    out[11]=0x4b78u-0x46f6u;
#endif
    out[14]=R32(0x50090088u);
    if(out[5]==0xaaaaaaaau && out[6]==0xb468u) {
        volatile uint16_t *payload=(volatile uint16_t *)(out+16u);
        unsigned offset=0u;
        for(unsigned block=0;block<3u;block++) {
            uint32_t local=out[8u+2u*block],bytes=out[9u+2u*block];
            for(unsigned i=0;i<bytes/2u;i++)
                payload[offset++]=R16(0x50000000u+local+2u*i);
        }
        for(;offset<(RF_CODE_SNAPSHOT_BYTES-64u)/2u;offset++)payload[offset]=0u;
        out[3]=4u;
    } else out[3]=2u;
    out[15]=R32(0x50090088u);
    out[0]=0x31434652u; /* RFC1 */
    clean_range((uint32_t)out,RF_CODE_SNAPSHOT_BYTES);
}
#else
#define terminal_rf_code_snapshot_begin() ((void)0)
#define terminal_rf_code_snapshot() ((void)0)
#endif
static __attribute__((noinline,noclone)) void terminal_rf_phase_log_begin(void) {
    for(unsigned i=0;i<RF_PHASE_LOG_WORDS;i++)RF_PHASE_LOG[i]=0u;
    RF_PHASE_LOG[1]=1u;RF_PHASE_LOG[2]=TERM_GENERATION;
#if defined(RXCAPT_RF_NATIVE_MARKER) && RXCAPT_RF_NATIVE_MARKER
    RF_PHASE_LOG[1]=2u;
#endif
#if defined(RXCAPT_RF_RXON_COEFF_STAMP) && RXCAPT_RF_RXON_COEFF_STAMP
    RF_PHASE_LOG[1]=3u;
#endif
#if defined(RXCAPT_RF_RXON_REQUEST_STAMP) && RXCAPT_RF_RXON_REQUEST_STAMP
    RF_PHASE_LOG[1]=4u;
#endif
#if defined(RXCAPT_RF_FREQUENCY_STAMP) && RXCAPT_RF_FREQUENCY_STAMP
    RF_PHASE_LOG[1]=5u; /* Header words 7..11: one calculator witness per stage. */
#endif
#if defined(RXCAPT_RF_RXON_PREPARE_STAMP) && RXCAPT_RF_RXON_PREPARE_STAMP
    RF_PHASE_LOG[1]=6u; /* Word55 is now completion of all post-coefficient prepare stores. */
#endif
#if defined(RXCAPT_RF_RXON_FINISH_STAMP) && RXCAPT_RF_RXON_FINISH_STAMP
    RF_PHASE_LOG[1]=7u; /* Words53..55 are now full RXON finish/error/valid. */
#endif
    RF_PHASE_LOG[3]=5u;RF_PHASE_LOG[4]=RF_PHASE_ROW_WORDS;
    RF_PHASE_LOG[6]=CFG[9]?CFG[9]:terminal_profile_anchor(CFG[3]);
    RF_PHASE_LOG[0]=0x31504652u; /* RFP1 */
    clean_range((uint32_t)RF_PHASE_LOG,RF_PHASE_LOG_WORDS*4u);
    terminal_rf_code_snapshot_begin();
}
/* External linkage keeps the bounds guard in the compiled function even when
 * this translation unit's fixed call sites only supply stages 1..5. */
__attribute__((noinline,noclone)) void terminal_rf_phase_log(
    uint32_t stage,uint32_t data_count,uint32_t head_count) {
    if(stage<1u || stage>5u || RF_PHASE_LOG[0]!=0x31504652u)return;
    volatile uint32_t *out=RF_PHASE_LOG+16u+(stage-1u)*RF_PHASE_ROW_WORDS;
    if(out[1])return;
    out[0]=stage;out[1]=1u;
    out[2]=R32(0x50090088u);out[4]=data_count;out[5]=head_count;
    out[6]=R32(0x50007e10u);out[7]=R32(0x50007e14u);
    if(out[6]!=0xaaaaaaaau || out[7]!=0xb468u){out[1]=2u;goto done;}
    out[47]=1u;
    out[8]=R16(0x5000b530u);out[9]=R16(0x5000b538u);
    out[10]=R16(0x5000b544u);out[11]=R16(0x5000b546u);
    out[12]=R32(0x5000b53cu);out[13]=R32(0x5000b540u);
    out[14]=R16(0x5000b520u);out[15]=R16(0x5000b524u);
    out[16]=R16(0x5000b522u);out[17]=R16(0x5000b526u);
    out[18]=R16(0x5000b464u);out[43]=R32(0x804ed5c8u);
    out[47]|=2u;
#if defined(RXCAPT_RF_NATIVE_MARKER) && RXCAPT_RF_NATIVE_MARKER
    /* Only enable with the separately verified boot-loaded native prefix. */
    out[53]=R32(0x500066b0u);out[54]=R32(0x500066b4u);out[55]=R32(0x500066b8u);
#endif
#if defined(RXCAPT_RF_RXON_COEFF_STAMP) && RXCAPT_RF_RXON_COEFF_STAMP
    out[55]=R32(0x500066a0u);
#endif
#if defined(RXCAPT_RF_RXON_REQUEST_STAMP) && RXCAPT_RF_RXON_REQUEST_STAMP
    out[53]=R32(0x500066a4u);out[54]=R32(0x500066a8u);
#endif
#if defined(RXCAPT_RF_FREQUENCY_STAMP) && RXCAPT_RF_FREQUENCY_STAMP
    RF_PHASE_LOG[6u+stage]=R32(0x500066acu);
#endif
#if defined(RXCAPT_RF_RXON_FINISH_STAMP) && RXCAPT_RF_RXON_FINISH_STAMP
    out[53]=R32(0x50006694u);out[54]=R32(0x50006698u);out[55]=R32(0x5000669cu);
#endif
    if(out[9]>20u || out[10]>=15u){out[1]=3u;goto done;}
    unsigned index=15u*out[9]+out[10];
    out[46]=index;
    out[28]=R16(0x50008764u+2u*index);
    out[29]=R16(0x50009438u+2u*index);
    out[30]=R16(0x5000af78u+4u*index);
    out[31]=R16(0x5000af7au+4u*index);
    out[47]|=16u;
    out[19]=R16(0x50030008u);out[20]=R16(0x50030050u);
    out[21]=R16(0x50030054u);out[22]=R16(0x50030058u);
    out[47]|=4u;
    unsigned group_b=out[9]<=12u || out[9]==17u;
    uint32_t gate=group_b?0x50030364u:0x50030374u;
    uint32_t q8=group_b?0x50030360u:0x50030370u;
    uint32_t low=group_b?0x500302c4u:0x50032228u;
    uint32_t high=group_b?0x500302c8u:0x5003222cu;
    out[32]=gate;
    out[23]=R16(gate);out[24]=R16(q8);out[25]=R16(low);out[26]=R16(high);
    out[27]=R32(0x50032004u);
    out[47]|=8u;
    /* Bookends detect observed changes, not RF-core ownership or atomicity. */
    out[38]=R16(gate);out[39]=R32(0x50032004u);
    out[40]=R16(q8);out[41]=R16(low);out[42]=R16(high);
    out[36]=R16(0x50030050u);out[48]=R16(0x50030008u);
    out[49]=R16(0x50030058u);out[50]=R16(0x50030054u);
    out[33]=R16(0x5000b538u);out[34]=R32(0x5000b544u);
    out[35]=R16(0x5000b530u);out[37]=R32(0x5000b53cu);
    out[51]=R32(0x5000b540u);out[52]=R16(0x5000b464u);
    out[44]=R32(0x50007e10u);out[45]=R32(0x50007e14u);
    out[1]=(out[9]==out[33] && (out[10]|(out[11]<<16))==out[34] &&
        out[8]==out[35] && out[12]==out[37] && out[13]==out[51] &&
        out[18]==out[52] && out[19]==out[48] && out[20]==out[36] &&
        out[21]==out[50] && out[22]==out[49] && out[23]==out[38] &&
        out[27]==out[39] && out[24]==out[40] && out[25]==out[41] &&
        out[26]==out[42] && out[6]==out[44] && out[7]==out[45])?5u:4u;
done:
    out[3]=R32(0x50090088u);
    clean_range((uint32_t)out,RF_PHASE_ROW_WORDS*4u);
    RF_PHASE_LOG[5]|=1u<<(stage-1u);
    clean_range((uint32_t)RF_PHASE_LOG,64u);
}
#else
#define terminal_rf_phase_log_begin() ((void)0)
#define terminal_rf_phase_log(stage,data_count,head_count) ((void)0)
#define terminal_rf_code_snapshot() ((void)0)
#endif
#endif
