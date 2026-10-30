#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../../firmware/capture/rxcapt_stream_batch.h"
static uint32_t state[30];
static uint32_t *row(uint32_t n) {return state+9+(n%7)*3;}
static void setup(uint32_t released,uint32_t held,uint32_t published)
{
    memset(state,0,sizeof(state));state[0]=0x53545231;state[1]=1;state[2]=7;state[6]=published;state[7]=released;
    for(unsigned i=0;i<7;++i)state[9+i*3]=UINT32_MAX;
    for(uint32_t n=released;n<published;++n){row(n)[0]=n;row(n)[1]=n<held?4:0;row(n)[2]=3;}
}
static void rejects(uint32_t end)
{
    uint32_t before[30],claimed=0xabcdef;memcpy(before,state,sizeof(state));
    assert(!rxcapt_stream_exchange_batch(state,end,&claimed));
    assert(!memcmp(before,state,sizeof(state)) && claimed==0xabcdef);
}
int main(void)
{
    unsigned cases=0;
    /* All occupancy, held-prefix, release-prefix and physical-wrap positions.
     * Independent expected result checks every byte of the ring metadata. */
    for(uint32_t first=0;first<21;++first)
    for(uint32_t count=0;count<=7;++count)
    for(uint32_t held=0;held<=count;++held)
    for(uint32_t freed=0;freed<=held;++freed) {
        setup(first,first+held,first+count);
        uint32_t expected[30];memcpy(expected,state,sizeof(state));expected[7]=first+freed;
        for(uint32_t n=first;n<first+count;++n) {
            uint32_t *p=expected+9+(n%7)*3;
            if(n<first+freed){p[0]=UINT32_MAX;p[1]=p[2]=0;}else p[1]=4;
        }
        uint32_t claimed=UINT32_MAX;
        assert(rxcapt_stream_exchange_batch(state,first+freed,&claimed));
        assert(claimed==first+count && !memcmp(expected,state,sizeof(state)));++cases;
        /* Replaying the primitive is idempotent; mailbox sequence handling
         * still must guarantee duplicate commands replay the original reply. */
        assert(rxcapt_stream_exchange_batch(state,first+freed,&claimed));
        assert(!memcmp(expected,state,sizeof(state)));
    }
    setup(7,9,11);rejects(6);rejects(12);rejects(10); /* cannot release READY */
    setup(7,9,11);row(10)[2]=1;rejects(8); /* later unpaired row => no partial free */
    setup(7,9,11);row(10)[0]=9;rejects(8);
    setup(7,9,11);row(10)[1]=4;rejects(8); /* HOST after READY */
    setup(7,9,11);row(10)[1]=5;rejects(8); /* DMA bit still active */
    setup(7,9,11);state[2]=8;rejects(8);
    setup(7,9,11);state[7]=12;rejects(12);
    setup(UINT32_MAX-2,UINT32_MAX-1,UINT32_MAX);rejects(UINT32_MAX-1);
    setup(UINT32_MAX-4,UINT32_MAX-3,UINT32_MAX-1);
    uint32_t claimed=0;assert(rxcapt_stream_exchange_batch(state,UINT32_MAX-3,&claimed));assert(claimed==UINT32_MAX-1);
    assert(!rxcapt_stream_exchange_batch(NULL,0,&claimed));assert(!rxcapt_stream_exchange_batch(state,state[7],NULL));
    printf("exchange passed: %u occupancy/ownership/wrap cases plus malformed, no-partial-mutation, replay and overflow checks\n",cases);
    return 0;
}
