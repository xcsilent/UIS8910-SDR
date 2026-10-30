#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "cp_usb_stream.h"

static void ignore(void *c,const volatile void *p,uint32_t n){(void)c;(void)p;(void)n;}
static void barrier(void *c){(void)c;}
int main(void) {
    _Alignas(32) uint32_t progress[8]={0x54524d31u,123,0,30,0};
    _Alignas(32) uint32_t ring[32]={0x53545231u,1,6,1};
    struct cp_mailbox_cache cache={0,ignore,ignore,barrier};
    struct cp_capture_snapshot out;
    uint32_t drops=999;
    ring[28]=3;
    assert(cp_capture_snapshot_read(progress,ring,123,cache,&out) && !out.dma_idle);
    assert(!cp_capture_final_scratch_drops(progress,ring,123,cache,&drops) && drops==999);
    ring[28]=1;
    assert(cp_capture_snapshot_read(progress,ring,123,cache,&out) && !out.dma_idle);
    ring[28]=0;
    ring[29]=37;
    assert(cp_capture_snapshot_read(progress,ring,123,cache,&out) && out.dma_idle);
    assert(cp_capture_final_scratch_drops(progress,ring,123,cache,&drops) && drops==37);
    ring[3]=0;
    assert(!cp_capture_final_scratch_drops(progress,ring,123,cache,&drops));
    ring[3]=1;
    ring[2]=7;
    assert(!cp_capture_snapshot_read(progress,ring,123,cache,&out));
    puts("six-slot snapshots keep scratch DMA ownership");
}
