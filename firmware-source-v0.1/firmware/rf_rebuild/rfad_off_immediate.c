#include "rfad_off_immediate.h"

static uint32_t rd(const struct rf_bus *b,uint32_t a,unsigned n){return b->read(b->context,a,n);}
static int ram(uint32_t a,uint32_t n){return !(a&3u) && a>=UINT32_C(0x80000000) && a<=UINT32_C(0x80970000)-n;}

enum rfad_frame_time_result rfad_off_immediate_bounded(
    const struct rf_bus *b,const struct rfad_off_immediate_context *c,
    uint32_t card,uint32_t limit,uint32_t *completed) {
    if(!b || !b->read || !b->write || !c || !completed || card>1 || !limit || limit>4096 ||
       !ram(c->info,44) || !ram(c->rx_info,40) || !ram(c->tx_info,40) ||
       !ram(c->rfnv,0x4000) || !ram(c->cursor,0x30))return RFAD_FRAME_TIME_BAD_ARGUMENT;
    if(rd(b,c->info+4,2)>=27)return RFAD_FRAME_TIME_BAD_ARGUMENT;
    *completed=0;
    for(unsigned step=0;step<6;step++) {
        uint32_t command;
        if(step<2) {
            uint32_t band=rd(b,c->info+4,2);
            uint32_t soft=rd(b,c->info+6,1);
            uint32_t bw=rd(b,(step?c->tx_info+0x10:c->rx_info+0x1c),2);
            uint32_t port=rd(b,c->rfnv+(step?0xf2u:0xf0u)+4*band,2);
            command=((soft<<8)|(port<<4)|bw)&65535u;
            command|=step?UINT32_C(0x240000):UINT32_C(0x0c0000);
        } else if(step==2 || step==4) {
            uint32_t soft=rd(b,c->info+6,2);
            command=(step==2?UINT32_C(0x2c8007):UINT32_C(0x2c8001))|(soft<<4);
        } else {
            uint32_t band=rd(b,c->info+4,2);
            uint32_t address=c->rfnv+4*band+(step==3?0x1788u:0x1488u);
            uint32_t high=rd(b,address,1);
            uint32_t low=rd(b,address+2,2);
            command=UINT32_C(0x440000)|((low|(high<<8))&65535u);
        }
        enum rfad_frame_time_result result=rfad_spi_write_bounded(
            b,c->rfnv,c->cursor,command,card,limit);
        if(result!=RFAD_FRAME_TIME_OK)return result;
        *completed=step+1;
    }
    return RFAD_FRAME_TIME_OK;
}
