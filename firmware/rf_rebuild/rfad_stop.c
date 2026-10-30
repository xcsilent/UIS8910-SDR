#include "rfad_stop.h"
static uint32_t rd(const struct rf_bus *b, uint32_t a, unsigned n) { return b->read(b->context,a,n); }
static void wr(const struct rf_bus *b, uint32_t a, uint32_t v, unsigned n) { b->write(b->context,a,v,n); }

void rfad_rxoff_parameters(const struct rf_bus *b, const struct rfad_rx_context *c, uint32_t slots) {
    uint32_t dest=rd(b,slots+8,4);
    uint32_t band=rd(b,c->info+4,2);
    uint32_t soft=rd(b,c->info+6,1);
    uint32_t port=rd(b,c->rfnv+0xf0+4*band,2);
    uint32_t bw=rd(b,c->rx_info+28,2);
    wr(b,dest,UINT32_C(0x000c0000)|(((soft<<8)|(port<<4)|bw)&65535u),4);
}
void rfad_reset_memory(const struct rf_bus *b, uint32_t context, uint32_t mode) {
    uint32_t bit=mode==1?1u:2u;
    uint32_t base=mode==1?UINT32_C(0x25101580):UINT32_C(0x25102580);
    uint32_t cursor=context+(mode==1?0x20u:0x24u);
    uint32_t pointer=context+(mode==1?0x18u:0x1cu);
    uint32_t v=rd(b,UINT32_C(0x25100000),4);
    wr(b,UINT32_C(0x25100000),v&~bit,4);
    wr(b,cursor,0,4);
    wr(b,pointer,base,4);
    v=rd(b,cursor,4);
    wr(b,base+4*v,UINT32_MAX,4);
    v=rd(b,UINT32_C(0x25100000),4);
    wr(b,UINT32_C(0x25100000),v|bit,4);
}
void rfad_txrx_rx_stop(const struct rf_bus *b) {
    uint32_t v=rd(b,UINT32_C(0x25000014),4);
    wr(b,UINT32_C(0x25000014),v|1u,4);
}
uint32_t rfad_dma_count(const struct rf_bus *b, uint32_t table, uint32_t channel) {
    uint32_t base=rd(b,table+4*channel,4);return rd(b,base+0x10,4);
}
void rfad_dma_clear_count(const struct rf_bus *b, uint32_t table, uint32_t channel) {
    uint32_t base=rd(b,table+4*channel,4);wr(b,base+0x10,0,4);
}
uint32_t rfad_dma_started(const struct rf_bus *b, uint32_t table, uint32_t channel) {
    uint32_t base=rd(b,table+4*channel,4);return rd(b,base,4)&1u;
}
void rfad_dma_release_bit(const struct rf_bus *b, uint32_t flags, uint32_t channel) {
    uint32_t v=rd(b,flags,2);wr(b,flags,v&~(1u<<channel)&65535u,2);
}
enum rfad_dma_stop_result rfad_dma_stop_bounded(const struct rf_bus *b, uint32_t table,
    uint32_t channel, uint32_t clear_count, uint32_t poll_limit) {
    if(channel>=12 || clear_count>1 || !poll_limit || poll_limit>4096 || (table&3u) ||
       table<UINT32_C(0x80000000) || table>UINT32_C(0x80970000)-48)return RFAD_DMA_BAD_ARGUMENT;
    uint32_t cell=table+4*channel;
    uint32_t expected=UINT32_C(0x22000040)+64*channel;
    uint32_t base=rd(b,cell,4);
    if(base!=expected)return RFAD_DMA_BAD_LAYOUT;
    uint32_t conf=rd(b,base,4);wr(b,base,conf&~1u,4);
    base=rd(b,cell,4);
    if(base!=expected)return RFAD_DMA_BAD_LAYOUT;
    for(uint32_t i=0;i<poll_limit;i++) {
        uint32_t status=rd(b,base+0x18,4);
        if(!(status&1u)) {
            if(clear_count) {
                wr(b,base+0x10,0,4);base=rd(b,cell,4);
                if(base!=expected)return RFAD_DMA_BAD_LAYOUT;
            }
            wr(b,base+4,65535u,4);return RFAD_DMA_QUIET;
        }
    }
    return RFAD_DMA_TIMEOUT;
}
