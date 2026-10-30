#include "rfad_frame_time.h"

static uint32_t read32(const struct rf_bus *b,uint32_t a){return b->read(b->context,a,4);}
static int valid(const struct rf_bus *b,uint32_t card,uint32_t limit){
    return b && b->read && card<=1 && limit && limit<=4096;
}

enum rfad_frame_time_result rfad_read_frame_time_bounded(
    const struct rf_bus *b,uint32_t card,uint32_t limit,struct rfad_frame_time *out) {
    if(!valid(b,card,limit) || !out)return RFAD_FRAME_TIME_BAD_ARGUMENT;
    uint32_t base=UINT32_C(0x50090000)+(card?0x2cu:0u);
    uint32_t i;
    for(i=0;i<limit;i++) {
        uint32_t current=read32(b,base+0xc0u);
        uint32_t length=read32(b,base+0xc4u);
        if(length<=50u)return RFAD_FRAME_TIME_BAD_CLOCK;
        if(current<=length-50u)break;
    }
    if(i==limit)return RFAD_FRAME_TIME_TIMEOUT;
    uint32_t cycle=read32(b,base+0xb8u)&1023u;
    uint32_t packed=read32(b,base+0xbcu)&65535u;
    uint32_t sfn=packed>>4,asfn=packed&15u;
    if(sfn>=1024u || asfn>=10u)return RFAD_FRAME_TIME_BAD_CLOCK;
    uint32_t offset=read32(b,base+0xc0u)&65535u;
    /* Commit only after all reads/validation; timeout leaves output intact. */
    out->cycle=(uint16_t)cycle;
    out->ssfn=(uint16_t)(10*sfn+asfn);
    out->sfn=(uint16_t)sfn;
    out->asfn=(uint16_t)asfn;
    out->offset=(uint16_t)offset;
    return RFAD_FRAME_TIME_OK;
}

enum rfad_frame_time_result rfad_wait_frame_ticks_bounded(
    const struct rf_bus *b,uint32_t card,uint32_t ticks,uint32_t limit) {
    if(!valid(b,card,limit))return RFAD_FRAME_TIME_BAD_ARGUMENT;
    if(!ticks)return RFAD_FRAME_TIME_OK;
    uint32_t base=UINT32_C(0x50090000)+(card?0x2cu:0u);
    uint32_t length=read32(b,base+0xc4u)&65535u;
    uint32_t start=read32(b,base+0xc0u)&65535u;
    if(!length || start>length || ticks>length)return RFAD_FRAME_TIME_BAD_CLOCK;
    for(uint32_t i=0;i<limit;i++) {
        uint32_t current=read32(b,base+0xc0u)&65535u;
        if(current>length)return RFAD_FRAME_TIME_BAD_CLOCK;
        uint32_t elapsed=(current>=start?current:current+length)-start;
        if((elapsed&65535u)>=ticks)return RFAD_FRAME_TIME_OK;
    }
    return RFAD_FRAME_TIME_TIMEOUT;
}
