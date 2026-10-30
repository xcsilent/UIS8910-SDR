#include "cp_usb_stream.h"
#include "../capture/rxcapt_finite_abi.h"
#include <stddef.h>

static void fetch(struct cp_mailbox_cache *c,volatile const uint32_t *address,uint32_t *out,unsigned words)
{
    c->invalidate(c->context,address,(words*4u+31u)&~31u);
    c->barrier(c->context);
    for (unsigned i=0;i<words;++i) out[i]=address[i];
}
int cp_capture_snapshot_read(volatile const uint32_t *progress,
    volatile const uint32_t *exported,uint32_t generation,
    struct cp_mailbox_cache cache,struct cp_capture_snapshot *out)
{
    if (!progress || !exported || !out || !generation || !cache.invalidate || !cache.barrier ||
        ((uintptr_t)progress&31u) || ((uintptr_t)exported&31u)) return 0;
    uint32_t p[8],p_after[8],header[8],after[8],idle=0;
    fetch(&cache,progress,p,8);
    if (p[0]!=0x54524d31u || p[1]!=generation || (p[2]&1u)) return 0;
    fetch(&cache,exported,header,8);
    if (header[0]!=0x53545231u || header[1]!=1u || header[2]!=SDR_RX_OUTPUT_SLOTS ||
        header[7]>header[6] || header[6]-header[7]>SDR_RX_OUTPUT_SLOTS) return 0;
    if ((header[3]&1u) && (p[3]==30u || p[3]==31u)) {
        uint32_t full[30];
        fetch(&cache,exported,full,30);
        idle=1;
        for (unsigned i=0;i<8;++i) if (full[i]!=header[i]) return 0;
        for (unsigned i=0;i<7;++i) if (full[10u+i*3u]&3u) idle=0;
    }
    fetch(&cache,exported,after,8);
    fetch(&cache,progress,p_after,8);
    for (unsigned i=0;i<8;++i) if (header[i]!=after[i] || p[i]!=p_after[i]) return 0;
    *out=(struct cp_capture_snapshot){generation,p[3],p[4],header[6],header[7],header[3],idle};
    return 1;
}
int cp_capture_final_scratch_drops(volatile const uint32_t *progress,
    volatile const uint32_t *exported,uint32_t generation,
    struct cp_mailbox_cache cache,uint32_t *drops)
{
    struct cp_capture_snapshot first,second;
    uint32_t a[32],b[32];
    if(!drops || SDR_RX_OUTPUT_SLOTS!=6u ||
       !cp_capture_snapshot_read(progress,exported,generation,cache,&first) ||
       !(first.flags&1u) || !first.dma_idle || (first.phase!=30u && first.phase!=31u))return 0;
    fetch(&cache,exported,a,30);fetch(&cache,exported,b,30);
    for(unsigned i=0;i<30;++i)if(a[i]!=b[i])return 0;
    if(a[0]!=0x53545231u || a[1]!=1u || a[2]!=6u || !(a[3]&1u) || (a[28]&3u))return 0;
    if(!cp_capture_snapshot_read(progress,exported,generation,cache,&second) ||
       first.generation!=second.generation || first.phase!=second.phase || first.flags!=second.flags ||
       first.published!=second.published || first.released!=second.released || !second.dma_idle)return 0;
    *drops=a[29];return 1;
}
