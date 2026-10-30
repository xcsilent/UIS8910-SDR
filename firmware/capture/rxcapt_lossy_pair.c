#include "rxcapt_lossy_pair.h"
#include "rxcapt_stream_idle.h"
#include <stdint.h>
#define MAGIC 0x53545231u
#define FREE UINT32_MAX
#define STOP 1u

static int valid(volatile uint32_t *r) {
    return r && r[0]==MAGIC && r[1]==1u && r[2]>=2u && r[2]<=7u &&
           r[7]<=r[6] && r[6]-r[7]<=r[2] && r[6]<UINT32_MAX-1u;
}
static void barrier(void) {
#if defined(__arm__)
    __asm__ volatile("dmb sy" ::: "memory");
#else
    __asm__ volatile("" ::: "memory");
#endif
}
uint32_t rxcapt_lossy_adopt_initial(volatile uint32_t *r,struct rxcapt_lossy_pair *p) {
    if(!valid(r) || !p || p->active || r[3] || r[4] || r[5] || r[6] || r[7] ||
       r[2]!=6u || r[9]!=0u || r[10]!=3u || r[11]!=0u || r[28] || r[29])return RX_LOSSY_ERROR;
    p->slot=0;p->completed=0;p->dropped_pairs=0;p->active=1;
    barrier();return RX_LOSSY_ARM;
}
uint32_t rxcapt_lossy_begin(volatile uint32_t *r,struct rxcapt_lossy_pair *p,
                            uint32_t scratch,uint32_t *slot) {
    if(!valid(r) || !p || !slot || p->active || r[2]!=6u || scratch!=6u)return RX_LOSSY_ERROR;
    if(r[3]&STOP)return RX_LOSSY_STOP;
    uint32_t index=r[6]%r[2];
    volatile uint32_t *row=r+9u+3u*index;
    if(row[0]==FREE && !row[1] && !row[2]) {
        row[0]=r[6];row[1]=3;row[2]=0;p->slot=index;
    } else {
        /* Seventh row is private scratch metadata, invisible to batch claim. */
        if(r[28]&3u)return RX_LOSSY_ERROR;
        r[28]=3u;p->slot=scratch;
    }
    p->completed=0;p->active=1;*slot=p->slot;
    barrier();return RX_LOSSY_ARM;
}
uint32_t rxcapt_lossy_complete(volatile uint32_t *r,struct rxcapt_lossy_pair *p,
                               uint32_t channel) {
    if(!valid(r) || !p || !p->active || channel>1u || (p->completed&(1u<<channel)))return RX_LOSSY_ERROR;
    uint32_t bit=1u<<channel;
    if(p->slot<r[2]) {
        volatile uint32_t *row=r+9u+3u*p->slot;
        if(p->slot!=r[6]%r[2] || row[0]!=r[6] || !(row[1]&bit) || (row[2]&bit))return RX_LOSSY_ERROR;
        row[1]&=~bit;row[2]|=bit;
    } else {
        if(p->slot!=6u || !(r[28]&bit))return RX_LOSSY_ERROR;
        r[28]&=~bit;
    }
    p->completed|=bit;
    if(p->completed!=3u){barrier();return RX_LOSSY_WAIT;}
    if(p->slot<r[2]) {barrier();++r[6];}
    else {
        if(p->dropped_pairs!=UINT32_MAX)++p->dropped_pairs;
        /* Scratch row is outside the six output rows. Count whole discarded
         * pairs only, saturating; it is not an estimate of exact lost samples. */
        r[29]=p->dropped_pairs;
    }
    p->active=0;barrier();return (r[3]&STOP)?RX_LOSSY_STOP:RX_LOSSY_WAIT;
}
uint32_t rxcapt_lossy_dma_idle(volatile uint32_t *r,const struct rxcapt_lossy_pair *p) {
    if(!valid(r) || !p || p->active)return 0;
    return rxcapt_rows_dma_idle(r,1u);
}
__attribute__((noinline))
uint32_t rxcapt_lossy_arm_reserved(const struct rxcapt_lossy_pair *p,
    uint32_t data,uint32_t head,uint32_t (*rearm)(uint32_t,uint32_t,uint32_t)) {
    if(!p || !p->active || p->completed || !rearm || data==head)return 0;
    if(!rearm(data,0u,p->slot))return 0;
    if(!rearm(head,1u,p->slot))return 0;
    return 1;
}
