#ifndef RXCAPT_RF_TARGET_REGISTER_SNAPSHOT_H
#define RXCAPT_RF_TARGET_REGISTER_SNAPSHOT_H
#if defined(RXCAPT_RF_TARGET_REGISTER_SNAPSHOT) && RXCAPT_RF_TARGET_REGISTER_SNAPSHOT
#define RF_TARGET_REGISTER_SNAPSHOT ((volatile uint32_t *)0x8096ea00u)
#define RF_TARGET_REGISTER_SNAPSHOT_BYTES 128u
#define RF_TARGET_REGISTER_SNAPSHOT_MAGIC 0x54524731u

/* Read selected unverified targets only after host STOP or safe ring-full
 * stop, RF teardown, and DMA idle. This never writes to RF or analog space. */
static void terminal_rf_target_register_snapshot_begin(void) {
    volatile uint32_t *out=RF_TARGET_REGISTER_SNAPSHOT;
    for(unsigned i=0;i<RF_TARGET_REGISTER_SNAPSHOT_BYTES/4u;i++)out[i]=0u;
    out[0]=RF_TARGET_REGISTER_SNAPSHOT_MAGIC;
    out[1]=1u;
    out[2]=TERM_GENERATION;
    clean_range((uint32_t)out,RF_TARGET_REGISTER_SNAPSHOT_BYTES);
}

static __attribute__((noinline,noclone)) void terminal_rf_target_register_snapshot(void) {
    volatile uint32_t *out=RF_TARGET_REGISTER_SNAPSHOT;
    if(out[0]!=RF_TARGET_REGISTER_SNAPSHOT_MAGIC || out[1]!=1u ||
       out[2]!=TERM_GENERATION || out[3]!=0u)return;
    out[3]=1u;
    out[4]=M[3];
    out[5]=STATE->phase;
    out[6]=STREAM[8];
    out[7]=M[2];
    out[8]=STATE->data_channel;
    out[9]=STATE->head_channel;
    out[10]=STATE->data_valid_bytes;
    out[11]=STATE->head_valid_bytes;
    uint32_t cpsr;
    __asm__ volatile("mrs %0,cpsr":"=r"(cpsr));
    out[12]=cpsr;
    if((cpsr&0xc0u)!=0xc0u || M[0]!=TERM_MAGIC || !M[2] ||
       M[3]!=T_HELD || STATE->phase!=RXCAPT_PHASE_HELD ||
       (STREAM[8]!=STREAM_REASON_HOST && STREAM[8]!=STREAM_REASON_FULL) ||
       STATE->data_channel<7u || STATE->data_channel>9u ||
       STATE->head_channel<7u || STATE->head_channel>9u ||
       STATE->data_channel==STATE->head_channel) {
        out[3]=3u;clean_range((uint32_t)out,RF_TARGET_REGISTER_SNAPSHOT_BYTES);return;
    }
    out[13]=R32(0x500a0024u);
    out[14]=R32(0x500a0028u);
    if(out[13]!=3u || out[14]!=3u) {
        out[3]=4u;clean_range((uint32_t)out,RF_TARGET_REGISTER_SNAPSHOT_BYTES);return;
    }
    uint32_t data=dma_channel_base(out[8]);
    uint32_t head=dma_channel_base(out[9]);
    if(!data || !head || data==head) {
        out[3]=4u;clean_range((uint32_t)out,RF_TARGET_REGISTER_SNAPSHOT_BYTES);return;
    }
    out[15]=R32(data);
    out[16]=R32(data+0x18u);
    out[17]=R32(head);
    out[18]=R32(head+0x18u);
    if((out[15]|out[16]|out[17]|out[18])&1u) {
        out[3]=4u;clean_range((uint32_t)out,RF_TARGET_REGISTER_SNAPSHOT_BYTES);return;
    }
    out[19]=R16(0x5003044cu);
    out[20]=R16(0x50030454u);
    out[21]=R16(0x50031040u);
    out[22]=R16(0x50032008u);
    out[23]=R16(0x5003201cu);
    out[24]=R16(0x50032020u);
    out[25]=R16(0x50032128u);
    out[26]=R32(0x50109050u);
    out[3]=2u;
    clean_range((uint32_t)out,RF_TARGET_REGISTER_SNAPSHOT_BYTES);
}
#endif
#endif
