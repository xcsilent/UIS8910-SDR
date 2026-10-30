#include "rfad_spi.h"

enum rfad_frame_time_result rfad_spi_write_bounded(
    const struct rf_bus *b,uint32_t nv,uint32_t context,uint32_t command,
    uint32_t card,uint32_t limit) {
    if(!b || !b->read || !b->write || card>1 || !limit || limit>4096 ||
       (nv&3u) || nv<UINT32_C(0x80000000) || nv>UINT32_C(0x80970000)-0xd4u ||
       (context&3u) || context<UINT32_C(0x80000000) ||
       context>UINT32_C(0x80970000)-0x30u)return RFAD_FRAME_TIME_BAD_ARGUMENT;
    uint32_t gpo=b->read(b->context,nv+0xd2u,2)&65535u;
    gpo&=b->read(b->context,nv+0xd0u,2)&65535u;
    gpo|=b->read(b->context,context+0x2cu,4);
    b->write(b->context,UINT32_C(0x25100008),gpo|UINT32_C(0x10000),4);
    b->write(b->context,UINT32_C(0x25100008),gpo|UINT32_C(0x18000),4);
    b->write(b->context,UINT32_C(0x2510000c),command,4);
    enum rfad_frame_time_result status=rfad_wait_frame_ticks_bounded(b,card,100u,limit);
    if(status!=RFAD_FRAME_TIME_OK)return status;
    gpo=b->read(b->context,context+0x2cu,4);
    b->write(b->context,UINT32_C(0x25100008),gpo|UINT32_C(0x10000),4);
    return RFAD_FRAME_TIME_OK;
}
