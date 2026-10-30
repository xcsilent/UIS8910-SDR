#include "rf_core_rxon_b.h"
#include "rf_core_rxon_prepare_b_mode.h"
#include "rf_core_tune_flow.h"
#include "rf_core_rxon_finish.h"
#include "rf_core_mode.h"

int rf_core_rxon_b(const struct rf_core_rxon_b_bus *bus, uint32_t rxon_context)
{
    struct rf_core_rxon_b_saved saved;
    uint16_t mode,word,flag,field,latch;
    int result;
    if (!bus || !bus->registers.read16 || !bus->registers.write16 ||
        !bus->calibration || !bus->mode) return -1;
    const struct rf_core_rxon_prepare_bus *b=&bus->registers;
#define READ(a,v) do { if (b->read16(b->context,(a),&(v))) return -2; } while (0)
#define WRITE(a,v) do { if (b->write16(b->context,(a),(uint16_t)(v))) return -2; } while (0)
    result=rf_core_rxon_prepare_b_enter(b,rxon_context,&saved);
    if (result) return result;
    READ(rxon_context,mode);
    result=rf_core_rxon_clock_mode(b,mode);
    if (result) return result;
    result=rf_core_rxon_prepare_b_commit(b);
    if (result) return result;
    result=rf_core_rxon_prepare_b_prefix(b,rxon_context);
    if (result) return result;
    result=rf_core_rxon_prepare_b_mode(b,rxon_context,saved.reg400,saved.reg404);
    if (result) return result;

    /* Original0x529c..0x5352 B completion latch, not A ready/timer tail. */
    WRITE(0x30364u,0x00b3); WRITE(0x30408u,0x4844);
    READ(0x304b4u,latch); READ(0xb52au,flag);
    if (!flag) WRITE(0x30498u,7);
    READ(rxon_context+4u,field); READ(0x8a54u+10u*field+8u,word);
    WRITE(0x30414u,word|0x40u); WRITE(0x304b4u,latch&~0x200u);
    WRITE(0x302ccu,0x60);
    READ(rxon_context+4u,field); READ(0x8a54u+10u*field+8u,word);
    WRITE(0x30414u,word|0x60u); WRITE(0x304b4u,latch|0x200u);
    if (bus->calibration(b->context,rxon_context)) return -3;
    READ(rxon_context,mode);
    if (bus->mode(b->context,mode)) return -4;
#undef READ
#undef WRITE
    return 0;
}

static int helpers_read16(void *p,uint32_t a,uint16_t *v)
{
    const struct rf_core_flow_bus *b=p;uint32_t word;
    if(b->read(b->context,a,2,&word))return -1;
    *v=(uint16_t)word;return 0;
}
static int helpers_write16(void *p,uint32_t a,uint16_t v)
{
    const struct rf_core_flow_bus *b=p;
    return b->write(b->context,a,2,v);
}
static int helpers_tables(void *p,uint32_t rxon_context)
{
    const struct rf_core_flow_bus *b=p;
    struct rf_core_rxon_finish_bus table_bus={b->context,b->read,b->write,0};
    return rf_core_rxon_apply_tables(&table_bus,rxon_context);
}
static int helpers_mode(void *p,uint16_t mode)
{
    const struct rf_core_flow_bus *b=p;
    struct rf_core_mode_bus mode_bus={b->context,b->read,b->write};
    return rf_core_apply_mode(&mode_bus,mode);
}
int rf_core_rxon_b_with_helpers(const struct rf_core_flow_bus *bus,
                                uint32_t rxon_context)
{
    if(!bus || !bus->read || !bus->write)return -1;
    struct rf_core_rxon_b_bus combined={{(void *)bus,helpers_read16,helpers_write16},
                                      helpers_tables,helpers_mode};
    return rf_core_rxon_b(&combined,rxon_context);
}

int rf_core_rxon_publish_state(const struct rf_core_rxon_publish_bus *bus)
{
    uint16_t word;
    if (!bus || !bus->registers.read16 || !bus->registers.write16 ||
        !bus->shared_acc) return -1;
    const struct rf_core_rxon_prepare_bus *b=&bus->registers;
#define READ(a,v) do { if (b->read16(b->context,(a),&(v))) return -2; } while (0)
#define WRITE(a,v) do { if (b->write16(b->context,(a),(uint16_t)(v))) return -2; } while (0)
    READ(0xb4eeu,word);
    if (word == 1u) {
        READ(0xb4d2u,word); WRITE(0xb4d2u,word|0x10u);
        if (bus->shared_acc(b->context)) return -3;
    }
    /* Deliberately re-read after the first helper: no cached flag/state. */
    READ(0xb4f2u,word);
    if (word == 1u) {
        READ(0xb4d2u,word); WRITE(0xb4d2u,word|0x20u);
        if (bus->shared_acc(b->context)) return -3;
    }
    WRITE(0xb52cu,1); READ(0xb52cu,word); WRITE(0xb4d8u,word);
    READ(0xb550u,word); WRITE(0xb4dcu,word);
#undef READ
#undef WRITE
    return 0;
}

int rf_core_rxon_record_timing(const struct rf_core_flow_bus *bus)
{
    uint32_t timer=0,index,frame,unused,low,high,i;
    if (!bus || !bus->read || !bus->write) return -1;
#define READ(a,w,v) do { if (bus->read(bus->context,(a),(w),&(v))) return -2; } while (0)
#define WRITE(a,w,v) do { if (bus->write(bus->context,(a),(w),(v))) return -2; } while (0)
    WRITE(0x500901f0u,4,0x100000u);
    for(i=0;i<10u;++i) {
        READ(0x500901f0u,4,timer);
        if (!(timer&0x100000u)) break;
    }
    timer &= 0x1ffffu;
    READ(0x92ceu,2,index); index &= 0xffffu;
    READ(0x50090104u,4,frame);
    WRITE(0x928cu+4u*index,4,(timer/24u & 0xffffu)|(frame<<16));
    /* Original0x902 performs all three reads, including the unused first. */
    READ(0x500900b8u,4,unused); (void)unused;
    READ(0x500900bcu,4,high); READ(0x500900c0u,4,low);
    WRITE(0x92a0u+4u*index,4,((high&0xffu)<<16)|(low&0xffffu));
    READ(0x92ceu,2,index);
    WRITE(0x92ceu,2,((index+1u)&0xffffu)%5u);
#undef READ
#undef WRITE
    return 0;
}
