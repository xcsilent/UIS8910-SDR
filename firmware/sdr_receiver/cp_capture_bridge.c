#include "cp_capture_bridge.h"
#include "../capture/rxcapt_finite_abi.h"

#define CP_DATA_BASE 0x80960000u
#define CP_DATA_BYTES RXCAPT_FINITE_DATA_BYTES
#define CP_SLOTS SDR_RX_OUTPUT_SLOTS

int cp_capture_bridge_init(struct cp_capture_bridge *b,struct iq_usb_ring *r,uint32_t generation)
{
    if (!b || !r || !generation ||
        !iq_usb_init(r,CP_DATA_BASE,CP_DATA_BYTES*CP_SLOTS,CP_DATA_BYTES,CP_SLOTS,generation)) return 0;
    *b=(struct cp_capture_bridge){0};
    b->ring=r; b->generation=generation;
    return 1;
}
uint32_t cp_capture_claim_credit(const struct cp_capture_bridge *b)
{
    if (!b || !b->ring || b->terminal_error || !b->ring->running || b->pending_release ||
        b->claimed<b->released || b->claimed-b->released>CP_SLOTS) return 0;
    return CP_SLOTS-(b->claimed-b->released);
}
void cp_capture_bridge_fail(struct cp_capture_bridge *b)
{
    b->terminal_error=1;
    /* READY blocks remain held by CP. USB-owned blocks remain USB-owned until
     * actual completion/cancellation. A failed session never reclaims CP
     * slots merely because the local ring has stopped.
     */
    iq_usb_stop(b->ring);
}
int cp_capture_claim_commit(struct cp_capture_bridge *b,uint32_t generation,uint32_t first,uint32_t end)
{
    if (!b || !b->ring || generation!=b->generation || first!=b->claimed || end<=first ||
        end>=UINT32_MAX || end-first>cp_capture_claim_credit(b)) return 0;
    struct iq_usb_ring *r=b->ring;
    for (uint32_t sequence=first;sequence<end;++sequence)
        if (r->slot[sequence%CP_SLOTS].state!=IQ_FREE) return 0;
    for (uint32_t sequence=first;sequence<end;++sequence) {
        /* CP operation 11 already established ownership; the local producer
         * imports that exact physical slot rather than choosing any free one.
         * Local tokens are CP sequence+1, reserving zero for uninitialized.
         */
        r->slot[sequence%CP_SLOTS]=(struct iq_slot){IQ_READY,sequence+1u,CP_DATA_BYTES};
        ++r->stats.acquired;
    }
    r->next_sequence=end+1u;
    b->claimed=end;
    ++b->claim_batches;
    return 1;
}
uint32_t cp_capture_release_begin(struct cp_capture_bridge *b)
{
    if (!b || !b->ring || b->terminal_error) return 0;
    if (b->pending_release) return b->pending_release;
    uint32_t end=b->released;
    for (;end<b->claimed;++end) {
        struct iq_slot *s=&b->ring->slot[end%CP_SLOTS];
        if (s->sequence!=end+1u || s->state!=IQ_FREE) break;
    }
    if (end==b->released) return 0;
    b->pending_release=end;
    return end;
}
int cp_capture_release_commit(struct cp_capture_bridge *b,uint32_t generation,uint32_t end)
{
    if (!b || !b->ring || b->terminal_error || generation!=b->generation ||
        !b->pending_release || end!=b->pending_release || end<=b->released || end>b->claimed) return 0;
    b->released=end;
    b->pending_release=0;
    ++b->release_batches;
    return 1;
}

int cp_capture_exchange_commit(struct cp_capture_bridge *b,uint32_t generation,uint32_t released,uint32_t end)
{
    if(!b || !b->ring || b->terminal_error || generation!=b->generation ||
       !b->ring->running || b->claimed<b->released || b->claimed-b->released>CP_SLOTS ||
       released!=(b->pending_release?b->pending_release:b->released) ||
       released<b->released || released>b->claimed || end<b->claimed ||
       end>=UINT32_MAX || end-released>CP_SLOTS)return 0;
    struct iq_usb_ring *r=b->ring;
    for(uint32_t n=b->released;n<released;++n)
        if(r->slot[n%CP_SLOTS].state!=IQ_FREE || r->slot[n%CP_SLOTS].sequence!=n+1u)return 0;
    for(uint32_t n=b->claimed;n<end;++n)
        if(r->slot[n%CP_SLOTS].state!=IQ_FREE)return 0;
    uint32_t first=b->claimed;
    if(released>b->released)++b->release_batches;
    b->released=released;b->pending_release=0;
    for(uint32_t n=first;n<end;++n) {
        r->slot[n%CP_SLOTS]=(struct iq_slot){IQ_READY,n+1u,CP_DATA_BYTES};
        ++r->stats.acquired;
    }
    if(end>first) {r->next_sequence=end+1u;++b->claim_batches;}
    b->claimed=end;
    return 1;
}
