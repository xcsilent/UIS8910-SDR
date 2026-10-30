#include "../../firmware/rf_rebuild/rf_core_rxon_prepare_b_prefix.h"
#include "../../firmware/rf_rebuild/rf_core_rxon_prepare_b_mode.h"
#include "../../firmware/rf_rebuild/rf_core_rxon_b.h"
#include "../../firmware/rf_rebuild/rf_core_tune_flow.h"

struct input { uint32_t field, factor, initial, fail_at; };
/* Trace every successful bus operation, including repeated context reads. */
struct output { int32_t result; uint32_t calls, count, trace[40][3]; };
struct context { const struct input *in; struct output *out; };

struct publish_input { uint32_t flag1,flag2,word,index,mutation,fail_at; };
struct publish_context {
    const struct publish_input *in;struct output *out;
    uint16_t word,flag2,active;
};
static int publish_access(struct publish_context *c,uint32_t op,uint32_t a,uint16_t *v) {
    if (++c->out->calls==c->in->fail_at) return -1;
    if (!op) {
        switch(a) {
        case 0xb4eeu:*v=(uint16_t)c->in->flag1;break;
        case 0xb4f2u:*v=c->flag2;break;
        case 0xb4d2u:*v=c->word;break;
        case 0xb52cu:*v=c->active;break;
        case 0xb550u:*v=(uint16_t)c->in->index;break;
        default:return -1;
        }
    } else if(op==1) {
        if(a==0xb4d2u)c->word=*v;
        else if(a==0xb52cu)c->active=*v;
        else if(a!=0xb4d8u && a!=0xb4dcu)return -1;
    }
    if(c->out->count>=40u)return -1;
    uint32_t *r=c->out->trace[c->out->count++];r[0]=op;r[1]=a;r[2]=*v;
    return 0;
}
static int publish_read(void *p,uint32_t a,uint16_t *v) {return publish_access(p,0,a,v);}
static int publish_write(void *p,uint32_t a,uint16_t v) {return publish_access(p,1,a,&v);}
static int publish_acc(void *p) {
    struct publish_context *c=p;uint16_t v=0;
    if(publish_access(c,2,0xaccu,&v))return -1;
    /* Synthetic helper effects ensure the caller re-reads shared state. */
    if(c->in->mutation) {c->word^=0x8000u;c->flag2=1u;}
    return 0;
}
int verify_rxon_publish(const struct publish_input *in,struct output *out) {
    out->calls=out->count=0;
    struct publish_context c={in,out,(uint16_t)in->word,(uint16_t)in->flag2,0xa55a};
    struct rf_core_rxon_publish_bus bus={{&c,publish_read,publish_write},publish_acc};
    out->result=rf_core_rxon_publish_state(&bus);return out->result;
}
int verify_rxon_publish_invalid(const struct publish_input *in,struct output *out) {
    out->calls=out->count=0;
    struct publish_context c={in,out,0,0,0};
    struct rf_core_rxon_publish_bus bus={{&c,publish_read,publish_write},publish_acc};
    if(in->flag1==1)bus.registers.read16=0;
    if(in->flag1==2)bus.registers.write16=0;
    if(in->flag1==3)bus.shared_acc=0;
    out->result=rf_core_rxon_publish_state(in->flag1==0 ? 0 : &bus);
    return out->result;
}

struct timing_input {
    uint32_t timer,busy_reads,index_first,index_last,frame,unused,high,low,fail_at;
};
struct timing_context {
    const struct timing_input *in;struct output *out;uint32_t timer_reads,index_reads;
};
static int timing_access(struct timing_context *c,uint32_t op,uint32_t a,
                         uint32_t width,uint32_t *v) {
    if(++c->out->calls==c->in->fail_at)return -1;
    if(!op) {
        switch(a) {
        case 0x500901f0u:*v=c->in->timer|(++c->timer_reads<=c->in->busy_reads ? 0x100000u : 0);break;
        case 0x92ceu:*v=c->index_reads++ ? c->in->index_last : c->in->index_first;break;
        case 0x50090104u:*v=c->in->frame;break;
        case 0x500900b8u:*v=c->in->unused;break;
        case 0x500900bcu:*v=c->in->high;break;
        case 0x500900c0u:*v=c->in->low;break;
        default:return -1;
        }
    }
    if(c->out->count>=40u)return -1;
    uint32_t *r=c->out->trace[c->out->count++];
    r[0]=op+(width==4 ? 2u : 0u);r[1]=a;r[2]=*v;
    return 0;
}
static int timing_read(void *p,uint32_t a,uint32_t w,uint32_t *v) {return timing_access(p,0,a,w,v);}
static int timing_write(void *p,uint32_t a,uint32_t w,uint32_t v) {return timing_access(p,1,a,w,&v);}
int verify_rxon_timing(const struct timing_input *in,struct output *out) {
    out->calls=out->count=0;struct timing_context c={in,out,0,0};
    struct rf_core_flow_bus bus={&c,timing_read,timing_write};
    out->result=rf_core_rxon_record_timing(&bus);return out->result;
}

struct post_input {
    uint32_t frequency,mode,selector,control,fail_at,centers[4],width;
};
struct post_context { const struct post_input *in; struct output *out; };
static int post_access(struct post_context *c,uint32_t op,uint32_t a,
                       uint32_t width,uint32_t *v) {
    if (++c->out->calls==c->in->fail_at) return -1;
    if (!op) {
        if (a==0x32004u && width==2) *v=c->in->control;
        else if (a==0xb538u && width==2) *v=c->in->selector;
        else if (a>=0x8530u && a<=0x853cu && width==4 && !(a&3u))
            *v=c->in->centers[(a-0x8530u)/4u];
        else if (a==0x91a0u+4u*c->in->mode && width==4) *v=c->in->width;
        else return -1;
    }
    if (c->out->count>=40u) return -1;
    uint32_t *r=c->out->trace[c->out->count++];
    r[0]=op+(width==4 ? 2u : 0u);r[1]=a;r[2]=*v;
    return 0;
}
static int post_read(void *p,uint32_t a,uint32_t width,uint32_t *v) {
    return post_access(p,0,a,width,v);
}
static int post_write(void *p,uint32_t a,uint32_t width,uint32_t v) {
    return post_access(p,1,a,width,&v);
}
int verify_rxon_post(const struct post_input *in,struct output *out) {
    out->calls=out->count=0;
    struct post_context c={in,out};
    struct rf_core_flow_bus bus={&c,post_read,post_write};
    out->result=rf_core_rxon_post_configure(&bus,in->frequency,(uint16_t)in->mode);
    return out->result;
}
static uint16_t table_value(uint32_t address) {
    return (uint16_t)((address*73u)^0x5a3cu);
}
static int access_word(struct context *c,uint32_t op,uint32_t address,uint16_t *value) {
    if (++c->out->calls==c->in->fail_at) return -1;
    if (op==0) {
        if (address==0xb534u) *value=(uint16_t)c->in->field;
        else if (address==0xb526u || address==0xb52au || address==0xb538u) *value=(uint16_t)c->in->factor;
        else if (address==0x30404u) *value=(uint16_t)(c->in->initial^0xffffu);
        else if (address==0x30410u || address==0x302c0u || address==0x3049cu ||
                 address==0x30400u || address==0x30480u)
            *value=(uint16_t)c->in->initial;
        else *value=table_value(address);
    }
    if(c->out->count>=40u)return -1;
    uint32_t *row=c->out->trace[c->out->count++];
    row[0]=op; row[1]=address; row[2]=*value;
    return 0;
}
static int read16(void *p,uint32_t address,uint16_t *value) {
    return access_word(p,0,address,value);
}
static int write16(void *p,uint32_t address,uint16_t value) {
    return access_word(p,1,address,&value);
}
int verify_prepare_b(const struct input *in,struct output *out) {
    out->calls=out->count=0;
    struct context c={in,out};
    struct rf_core_rxon_prepare_bus bus={&c,read16,write16};
    out->result=rf_core_rxon_prepare_b_prefix(&bus,0xb530u);
    return out->result;
}

int verify_prepare_b_enter(const struct input *in,struct output *out) {
    out->calls=out->count=0;
    struct context c={in,out};
    struct rf_core_rxon_prepare_bus bus={&c,read16,write16};
    struct rf_core_rxon_b_saved saved={0x1234,0x5678};
    out->result=rf_core_rxon_prepare_b_enter(&bus,0xb530u,&saved);
    /* Independent snapshot result slots, outside the bus trace count. */
    out->trace[39][0]=saved.reg400;out->trace[39][1]=saved.reg404;
    return out->result;
}
int verify_prepare_b_commit(const struct input *in,struct output *out) {
    out->calls=out->count=0;
    struct context c={in,out};
    struct rf_core_rxon_prepare_bus bus={&c,read16,write16};
    out->result=rf_core_rxon_prepare_b_commit(&bus);
    return out->result;
}
int verify_clock_mode(const struct input *in,struct output *out) {
    out->calls=out->count=0;
    struct context c={in,out};
    struct rf_core_rxon_prepare_bus bus={&c,read16,write16};
    out->result=rf_core_rxon_clock_mode(&bus,(uint16_t)in->field);
    return out->result;
}

struct mode_input { uint32_t mode,selector,analog_flag,digital_flag,saved400,saved404,fail_at; };
struct mode_context { const struct mode_input *in; struct output *out; };
static int mode_access(struct mode_context *c,uint32_t op,uint32_t address,uint16_t *value) {
    if (++c->out->calls==c->in->fail_at) return -1;
    if (!op) {
        switch (address) {
        case 0xb530u: *value=(uint16_t)c->in->mode; break;
        case 0xb538u: *value=(uint16_t)c->in->selector; break;
        case 0xb4e0u: *value=(uint16_t)c->in->analog_flag; break;
        case 0xb52au: *value=(uint16_t)c->in->digital_flag; break;
        default: return -1;
        }
    }
    if(c->out->count>=40u)return -1;
    uint32_t *row=c->out->trace[c->out->count++];
    row[0]=op;row[1]=address;row[2]=*value;
    return 0;
}
static int mode_read(void *p,uint32_t a,uint16_t *v) { return mode_access(p,0,a,v); }
static int mode_write(void *p,uint32_t a,uint16_t v) { return mode_access(p,1,a,&v); }
int verify_prepare_b_mode(const struct mode_input *in,struct output *out) {
    out->calls=out->count=0;
    struct mode_context c={in,out};
    struct rf_core_rxon_prepare_bus bus={&c,mode_read,mode_write};
    out->result=rf_core_rxon_prepare_b_mode(&bus,0xb530u,(uint16_t)in->saved400,(uint16_t)in->saved404);
    return out->result;
}

struct full_input {
    uint32_t mode,selector,field,analog_flag,digital_flag,factor,initial,fail_at,mode_after_cal;
};
struct full_output { int32_t result; uint32_t calls,count,trace[128][3]; };
struct full_context { const struct full_input *in; struct full_output *out; uint16_t mode; };
static int full_access(struct full_context *c,uint32_t op,uint32_t address,uint16_t *value) {
    if (++c->out->calls==c->in->fail_at) return -1;
    if (!op) {
        uint32_t i=c->out->count;
        while(i) {
            const uint32_t *r=c->out->trace[--i];
            if(r[0]==1u && r[1]==address) { *value=(uint16_t)r[2]; goto record; }
        }
        switch(address) {
        case 0xb530u: *value=c->mode; break;
        case 0xb534u: *value=(uint16_t)c->in->field; break;
        case 0xb538u: *value=(uint16_t)c->in->selector; break;
        case 0xb4e0u: *value=(uint16_t)c->in->analog_flag; break;
        case 0xb52au: *value=(uint16_t)c->in->digital_flag; break;
        case 0xb526u: *value=(uint16_t)c->in->factor; break;
        case 0x30404u: *value=(uint16_t)(c->in->initial^0xffffu); break;
        case 0x30400u: case 0x30480u: case 0x30410u: case 0x302c0u: case 0x3049cu:
            *value=(uint16_t)c->in->initial; break;
        default: *value=table_value(address); break;
        }
    }
record:
    if(c->out->count>=128u)return -1;
    uint32_t *r=c->out->trace[c->out->count++];r[0]=op;r[1]=address;r[2]=*value;
    return 0;
}
static int full_read(void *p,uint32_t a,uint16_t *v) { return full_access(p,0,a,v); }
static int full_write(void *p,uint32_t a,uint16_t v) { return full_access(p,1,a,&v); }
static int full_cal(void *p,uint32_t rxon_context) {
    struct full_context *c=p;uint16_t value=0;
    if(full_access(c,2,rxon_context,&value))return -1;
    if(c->in->mode_after_cal<=65535u)c->mode=(uint16_t)c->in->mode_after_cal;
    return 0;
}
static int full_mode(void *p,uint16_t mode) { return full_access(p,3,0x3a7cu,&mode); }
int verify_rxon_b(const struct full_input *in,struct full_output *out) {
    out->calls=out->count=0;
    struct full_context c={in,out,(uint16_t)in->mode};
    struct rf_core_rxon_b_bus bus={{&c,full_read,full_write},full_cal,full_mode};
    out->result=rf_core_rxon_b(&bus,0xb530u);
    return out->result;
}

/* Shared0x453c table application; synthetic table values, exact read order. */
#include "../../firmware/rf_rebuild/rf_core_rxon_finish.h"
struct tables_input { uint32_t mode,selector,slot,control,fail_at; };
struct tables_context { const struct tables_input *in; struct full_output *out; };
static int tables_read(void *p,uint32_t a,uint32_t width,uint32_t *value) {
    struct tables_context *c=p;
    if(width!=2 || ++c->out->calls==c->in->fail_at)return -1;
    switch(a) {
    case 0xb530u:*value=c->in->mode;break;
    case 0xb538u:*value=c->in->selector;break;
    case 0xb544u:*value=c->in->slot;break;
    case 0xb546u:*value=c->in->control;break;
    default:*value=table_value(a);break;
    }
    uint32_t *r=c->out->trace[c->out->count++];r[0]=0;r[1]=a;r[2]=*value;
    return 0;
}
static int tables_write(void *p,uint32_t a,uint32_t width,uint32_t value) {
    struct tables_context *c=p;
    if(width!=2 || ++c->out->calls==c->in->fail_at)return -1;
    uint32_t *r=c->out->trace[c->out->count++];r[0]=1;r[1]=a;r[2]=value;
    return 0;
}
int verify_rxon_tables(const struct tables_input *in,struct full_output *out) {
    out->calls=out->count=0;
    struct tables_context c={in,out};
    struct rf_core_rxon_finish_bus bus={&c,tables_read,tables_write,0};
    out->result=rf_core_rxon_apply_tables(&bus,0xb530u);
    return out->result;
}

/* Initial memory cells are copied once; subsequent reads observe actual prior
 * writes. This is not a per-operation expected-value playback. */
struct integrated_cell { uint32_t address,value; };
struct integrated_input { const struct integrated_cell *cells; uint32_t count,fail_at; };
struct integrated_output { int32_t result;uint32_t calls,count,trace[384][3]; };
struct integrated_context {
    const struct integrated_input *in;struct integrated_output *out;
    struct integrated_cell cells[256];uint32_t count;
};
static int integrated_access(struct integrated_context *c,uint32_t op,uint32_t a,
                              uint32_t width,uint32_t *v) {
    if((width!=2 && width!=4) || ++c->out->calls==c->in->fail_at)return -1;
    uint32_t parts=width/2,indices[2],value=0;
    for(uint32_t part=0;part<parts;++part) {
        uint32_t i;
        for(i=0;i<c->count && c->cells[i].address!=a+2*part;++i){}
        if(i==c->count) {
            if(!op || c->count>=256u)return -1;
            c->cells[i].address=a+2*part;c->cells[i].value=0;++c->count;
        }
        indices[part]=i;
        value|=(c->cells[i].value&65535u)<<(16*part);
    }
    if(!op)*v=value;
    else for(uint32_t part=0;part<parts;++part)
        c->cells[indices[part]].value=(*v>>(16*part))&65535u;
    if(c->out->count>=384u)return -1;
    uint32_t *r=c->out->trace[c->out->count++];r[0]=op+(width==4?2:0);r[1]=a;r[2]=*v;
    return 0;
}
static int integrated_read(void *p,uint32_t a,uint32_t w,uint32_t *v) {return integrated_access(p,0,a,w,v);}
static int integrated_write(void *p,uint32_t a,uint32_t w,uint32_t v) {return integrated_access(p,1,a,w,&v);}
int verify_rxon_integrated(const struct integrated_input *in,struct integrated_output *out) {
    out->calls=out->count=0;
    struct integrated_context c;c.in=in;c.out=out;c.count=0;
    if(in->count>256u) {out->result=-1;return -1;}
    for(uint32_t i=0;i<in->count;++i)c.cells[c.count++]=in->cells[i];
    struct rf_core_flow_bus bus={&c,integrated_read,integrated_write};
    out->result=rf_core_rxon_b_with_helpers(&bus,0xb530u);return out->result;
}
int verify_rxon_integrated_invalid(const struct integrated_input *in,struct integrated_output *out) {
    out->calls=out->count=0;
    struct integrated_context c;c.in=in;c.out=out;c.count=0;
    struct rf_core_flow_bus bus={&c,integrated_read,integrated_write};
    if(in->count==1)bus.read=0;
    if(in->count==2)bus.write=0;
    out->result=rf_core_rxon_b_with_helpers(in->count==0 ? 0 : &bus,0xb530u);
    return out->result;
}
int verify_rxon_request_integrated(const struct integrated_input *in,struct integrated_output *out) {
    out->calls=out->count=0;
    struct integrated_context c;c.in=in;c.out=out;c.count=0;
    if(in->count>256u) {out->result=-1;return -1;}
    for(uint32_t i=0;i<in->count;++i)c.cells[c.count++]=in->cells[i];
    struct rf_core_flow_bus bus={&c,integrated_read,integrated_write};
    out->result=rf_core_rxon_request_b(&bus);return out->result;
}
