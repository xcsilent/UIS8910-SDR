#include "../../firmware/rf_rebuild/rf_core_mode.h"

/* Freestanding ARM ABI used only by the offline differential verifier. */
struct input { uint32_t mode, flag, initial, fail_at, correction_index, selector; };
struct output { int32_t result; uint32_t calls, count; uint32_t trace[64][3]; };
struct context { const struct input *in; struct output *out; };
static int read_word(void *opaque,uint32_t address,uint32_t width,uint32_t *value)
{
    struct context *c=opaque;
    if (++c->out->calls==c->in->fail_at) return -1;
    if (width!=2 || (address!=0x32000u && address!=0x32004u && address!=0xb52au && address!=0xb550u && address!=0xb538u)) return -1;
    *value=address==0xb52au ? c->in->flag : address==0xb550u ? c->in->correction_index : address==0xb538u ? c->in->selector : c->in->initial;
    if(c->out->count>=64u)return -1;
    uint32_t *row=c->out->trace[c->out->count++];row[0]=0;row[1]=address;row[2]=*value;
    return 0;
}
static int write_word(void *opaque,uint32_t address,uint32_t width,uint32_t value)
{
    struct context *c=opaque;
    if (++c->out->calls==c->in->fail_at) return -1;
    if (width!=2 || c->out->count>=64u) return -1;
    uint32_t *row=c->out->trace[c->out->count++];
    row[0]=1;row[1]=address;row[2]=value;
    return 0;
}
int verify_mode(const struct input *in,struct output *out)
{
    out->calls=out->count=0;
    struct context c={in,out};
    struct rf_core_mode_bus bus={&c,read_word,write_word};
    out->result=rf_core_apply_mode(&bus,in->mode);
    return out->result;
}
