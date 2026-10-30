#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "cp_capture_bridge.h"
#include "rxcapt_stream_batch.h"
#include "rxcapt_finite_abi.h"

static uint32_t cp[30];
static struct iq_usb_ring ring;
static struct cp_capture_bridge bridge;
static uint32_t *row(uint32_t sequence) { return cp+9+(sequence%7)*3; }
static void setup(void)
{
    memset(cp,0,sizeof(cp));
    cp[0]=0x53545231; cp[1]=1; cp[2]=7;
    for(unsigned i=0;i<7;++i) row(i)[0]=UINT32_MAX;
    assert(cp_capture_bridge_init(&bridge,&ring,17));
}
static void produce(uint32_t first,uint32_t count)
{
    assert(first==cp[6] && first+count-cp[7]<=7);
    for(uint32_t i=first;i<first+count;++i) {
        uint32_t *r=row(i);
        assert(r[0]==UINT32_MAX && r[1]==0 && r[2]==0);
        r[0]=i; r[2]=3;
    }
    cp[6]=first+count;
}
static void claim(uint32_t first,uint32_t end)
{
    uint32_t actual=0;
    assert(rxcapt_stream_claim_batch(cp,first,&actual) && actual==end);
    assert(cp_capture_claim_commit(&bridge,17,first,end));
    for(uint32_t i=first;i<end;++i) assert(row(i)[1]==4);
}
static void release(uint32_t end)
{
    assert(cp_capture_release_begin(&bridge)==end);
    assert(cp_capture_release_begin(&bridge)==end); /* pending command is stable */
    assert(!cp_capture_claim_credit(&bridge));
    assert(!cp_capture_release_commit(&bridge,18,end));
    assert(!cp_capture_release_commit(&bridge,17,end+1));
    assert(rxcapt_stream_release_batch(cp,end));
    assert(cp_capture_release_commit(&bridge,17,end));
    assert(cp[7]==bridge.released);
}
int main(void)
{
    setup();
    produce(0,3);
    uint32_t snapshot[30],end=0;
    memcpy(snapshot,cp,sizeof(cp));
    assert(!rxcapt_stream_claim_batch(cp,1,&end)); /* cannot skip earlier READY */
    assert(!rxcapt_stream_release_batch(cp,1)); /* cannot release before claim */
    assert(!memcmp(snapshot,cp,sizeof(cp)));
    row(2)[1]=1; /* DMA still active: batch must not partly claim prefix */
    memcpy(snapshot,cp,sizeof(cp));
    assert(!rxcapt_stream_claim_batch(cp,0,&end));
    assert(!memcmp(snapshot,cp,sizeof(cp)) && row(0)[1]==0);
    row(2)[1]=0;
    claim(0,3);
    assert(!cp_capture_claim_commit(&bridge,16,3,4));
    struct iq_usb_request requests[7];
    for(unsigned i=0;i<3;++i) {
        assert(iq_usb_take(&ring,&requests[i]));
        assert(requests[i].dma_address==0x80960000+i*RXCAPT_FINITE_DATA_BYTES && requests[i].bytes==RXCAPT_FINITE_DATA_BYTES);
    }
    assert(!cp_capture_release_begin(&bridge));
    assert(iq_usb_complete(&ring,requests[2].token,1));
    assert(!cp_capture_release_begin(&bridge)); /* late completion cannot release earlier slots */
    assert(iq_usb_complete(&ring,requests[0].token,1));
    release(1);
    assert(row(1)[1]==4 && row(2)[1]==4); /* USB/CP ownership retained */
    assert(iq_usb_complete(&ring,requests[1].token,1));
    release(3);
    assert(ring.stats.completed_bytes==3u*RXCAPT_FINITE_DATA_BYTES);

    uint32_t sequence=3;
    for(unsigned cycle=0;cycle<10000;++cycle) {
        uint32_t count=2+(cycle%6);
        produce(sequence,count);
        claim(sequence,sequence+count);
        assert(!rxcapt_stream_release_batch(cp,sequence+count+1));
        for(unsigned i=0;i<count;++i) {
            assert(iq_usb_take(&ring,&requests[i]));
            assert(requests[i].dma_address==0x80960000+((sequence+i)%7)*RXCAPT_FINITE_DATA_BYTES);
            assert(row(sequence+i)[1]==4);
        }
        for(unsigned i=count;i>0;--i) {
            assert(iq_usb_complete(&ring,requests[i-1].token,1));
            if(i>1) assert(!cp_capture_release_begin(&bridge));
        }
        release(sequence+count);
        sequence+=count;
    }
    assert(bridge.claim_batches==10001 && bridge.release_batches==10002);
    assert(cp_capture_claim_credit(&bridge)==7 && bridge.released==sequence);
    assert(ring.stats.completed_bytes==(uint64_t)sequence*RXCAPT_FINITE_DATA_BYTES);

    /* One partial block prevents every mutation, including earlier ones. */
    produce(sequence,2); claim(sequence,sequence+2);
    row(sequence+1)[2]=1;
    memcpy(snapshot,cp,sizeof(cp));
    assert(!rxcapt_stream_release_batch(cp,sequence+2));
    assert(!memcmp(snapshot,cp,sizeof(cp)));
    cp_capture_bridge_fail(&bridge);
    assert(!cp_capture_claim_credit(&bridge));
    assert(!cp_capture_release_begin(&bridge));
    assert(row(sequence)[1]==4); /* failure cannot fabricate CP release */
    assert(!cp_capture_claim_commit(&bridge,17,sequence+2,sequence+3));

    printf("CP batch bridge passed: %u-byte DMA slots, multi-claim, atomic rejection, delayed/out-of-order USB completion, release acknowledgments, generation checks, 10000 wrap cycles; no payload access\n", (unsigned)RXCAPT_FINITE_DATA_BYTES);
    return 0;
}
