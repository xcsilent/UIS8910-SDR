#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "rxcapt_lossy_pair.h"
#include "rxcapt_stream_batch.h"
#include "rxcapt_stream_idle.h"

static uint32_t calls, fail_at;
static uint32_t mock_arm(uint32_t channel,uint32_t head,uint32_t slot) {
    assert(channel==(head?8u:7u) && slot==6u);++calls;
    return calls!=fail_at;
}
int main(void) {
    uint32_t r[30]={0}, slot=99, end=0;
    struct rxcapt_lossy_pair p={0};
    r[0]=0x53545231u;r[1]=1;r[2]=6;
    for(unsigned i=0;i<6;i++)r[9+3*i]=UINT32_MAX;
    r[9]=0;r[10]=3;
    assert(rxcapt_lossy_adopt_initial(r,&p)==RX_LOSSY_ARM);
    assert(rxcapt_lossy_adopt_initial(r,&p)==RX_LOSSY_ERROR);
    for(unsigned i=0;i<6;i++) {
        if(i)assert(rxcapt_lossy_begin(r,&p,6,&slot)==RX_LOSSY_ARM && slot==i);
        assert(rxcapt_lossy_complete(r,&p,i%2)==RX_LOSSY_WAIT && r[6]==i);
        assert(rxcapt_lossy_complete(r,&p,1-i%2)==RX_LOSSY_WAIT && r[6]==i+1);
    }
    assert(rxcapt_stream_exchange_batch(r,0,&end) && end==6);
    assert(rxcapt_lossy_begin(r,&p,6,&slot)==RX_LOSSY_ARM && slot==6);
    assert(!rxcapt_lossy_dma_idle(r,&p)); /* shared rows alone appear idle */
    assert(rxcapt_rows_dma_idle(r,0) && !rxcapt_rows_dma_idle(r,1));
    fail_at=1;calls=0;assert(!rxcapt_lossy_arm_reserved(&p,7,8,mock_arm) && calls==1 && r[28]==3);
    fail_at=2;calls=0;assert(!rxcapt_lossy_arm_reserved(&p,7,8,mock_arm) && calls==2 && r[28]==3);
    fail_at=0;calls=0;assert(rxcapt_lossy_arm_reserved(&p,7,8,mock_arm) && calls==2);
    assert(rxcapt_lossy_complete(r,&p,0)==RX_LOSSY_WAIT);
    assert(rxcapt_lossy_complete(r,&p,0)==RX_LOSSY_ERROR);
    r[3]=1;
    assert(!rxcapt_lossy_dma_idle(r,&p) && r[29]==0);
    assert(rxcapt_lossy_complete(r,&p,1)==RX_LOSSY_STOP && r[6]==6 && p.dropped_pairs==1 && r[29]==1);
    assert(rxcapt_rows_dma_idle(r,1));
    assert(rxcapt_lossy_dma_idle(r,&p));
    assert(rxcapt_lossy_begin(r,&p,6,&slot)==RX_LOSSY_STOP);
    r[3]=0; /* Separate synthetic scenario after stop checks. */
    assert(rxcapt_stream_exchange_batch(r,1,&end) && end==6);
    assert(rxcapt_lossy_begin(r,&p,6,&slot)==RX_LOSSY_ARM && slot==0);
    assert(rxcapt_lossy_complete(r,&p,1)==RX_LOSSY_WAIT);
    r[3]=1;
    assert(!rxcapt_lossy_dma_idle(r,&p));
    assert(rxcapt_lossy_complete(r,&p,0)==RX_LOSSY_STOP && r[6]==7);
    assert(rxcapt_lossy_dma_idle(r,&p));
    assert(rxcapt_lossy_begin(r,&p,6,&slot)==RX_LOSSY_STOP);
    assert(rxcapt_stream_exchange_batch(r,6,&end) && end==7);
    assert(rxcapt_stream_exchange_batch(r,7,&end) && end==7);
    uint32_t stop_polls=UINT32_MAX;
    assert(!rxcapt_lossy_stop_expired(0,&stop_polls) && !stop_polls);
    for(uint32_t i=1;i<RX_LOSSY_STOP_POLLS;i++) {
        /* Simulate continued command renewal: it cannot reset this budget. */
        assert(!rxcapt_lossy_stop_expired(1,&stop_polls) && stop_polls==i);
    }
    assert(rxcapt_lossy_stop_expired(1,&stop_polls));
    assert(rxcapt_lossy_stop_expired(1,&stop_polls) && stop_polls==RX_LOSSY_STOP_POLLS);
    assert(!rxcapt_lossy_stop_expired(0,&stop_polls) && !stop_polls);
    puts("paired scratch drop, ordered publish, wrap and stop passed");
}
