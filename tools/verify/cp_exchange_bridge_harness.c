#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../../firmware/sdr_receiver/cp_capture_bridge.h"
#include "../../firmware/capture/rxcapt_stream_batch.h"
static uint32_t cp[30];
static struct iq_usb_ring ring;
static struct cp_capture_bridge bridge;
static uint32_t *row(uint32_t n){return cp+9+(n%7)*3;}
static void setup(uint32_t first,uint32_t held,uint32_t published,uint32_t completed)
{
    memset(cp,0,sizeof(cp));cp[0]=0x53545231;cp[1]=1;cp[2]=7;cp[6]=published;cp[7]=first;
    for(unsigned i=0;i<7;++i)cp[9+3*i]=UINT32_MAX;
    assert(cp_capture_bridge_init(&bridge,&ring,123));
    bridge.released=first;bridge.claimed=held;
    for(uint32_t n=first;n<published;++n) {
        row(n)[0]=n;row(n)[1]=n<held?4:0;row(n)[2]=3;
        if(n<held)ring.slot[n%7]=(struct iq_slot){n<completed?IQ_FREE:IQ_USB,n+1,8000};
    }
    assert(cp_capture_release_begin(&bridge)==(completed>first?completed:0));
}
static void rejects(uint32_t generation,uint32_t released,uint32_t claimed)
{
    struct iq_usb_ring old=ring;struct cp_capture_bridge before=bridge;
    assert(!cp_capture_exchange_commit(&bridge,generation,released,claimed));
    assert(!memcmp(&ring,&old,sizeof(ring)) && !memcmp(&bridge,&before,sizeof(bridge)));
}
int main(void)
{
    unsigned cases=0;
    for(uint32_t first=0;first<21;++first)
    for(uint32_t count=0;count<=7;++count)
    for(uint32_t held=0;held<=count;++held)
    for(uint32_t done=0;done<=held;++done) {
        setup(first,first+held,first+count,first+done);
        uint32_t end=0;assert(rxcapt_stream_exchange_batch(cp,first+done,&end));
        assert(cp_capture_exchange_commit(&bridge,123,first+done,end));
        assert(bridge.released==cp[7] && bridge.claimed==cp[6] && !bridge.pending_release);
        for(uint32_t n=first+done;n<first+count;++n) {
            assert(row(n)[0]==n && row(n)[1]==4 && row(n)[2]==3);
            assert(ring.slot[n%7].sequence==n+1);
            assert(ring.slot[n%7].state==(n<first+held?IQ_USB:IQ_READY));
        }
        assert(ring.stats.acquired==count-held);++cases;
    }
    setup(7,10,12,9);rejects(122,9,12);rejects(123,8,12);rejects(123,9,9);rejects(123,9,17);
    setup(7,10,12,9);ring.slot[11%7].state=IQ_USB;rejects(123,9,12); /* invalid new slot => no partial release */
    setup(7,10,12,9);ring.slot[8%7].state=IQ_USB;rejects(123,9,12); /* false completion */
    setup(7,10,12,9);bridge.terminal_error=1;rejects(123,9,12);
    setup(7,10,12,9);ring.running=0;rejects(123,9,12);
    setup(7,10,12,9);rejects(123,9,UINT32_MAX);
    printf("AP/CP exchange composition passed: %u paired ownership/wrap cases and atomic malformed-reply rejection\n",cases);
    return 0;
}
