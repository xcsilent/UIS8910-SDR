#include "rxcapt_stream_batch.h"

#define MAGIC 0x53545231u
#define HOST 4u
#define PAIRED 3u
#define FREE UINT32_MAX

static void barrier(void)
{
#if defined(__arm__)
    __asm__ volatile("dmb sy" ::: "memory");
#else
    __asm__ volatile("" ::: "memory");
#endif
}
static int valid(volatile uint32_t *s)
{
    return s && s[0]==MAGIC && s[1]==1u && s[2]>=2u && s[2]<=7u &&
           s[7]<=s[6] && s[6]-s[7]<=s[2];
}
static volatile uint32_t *slot(volatile uint32_t *s,uint32_t sequence)
{ return s+9u+(sequence%s[2])*3u; }

uint32_t rxcapt_stream_claim_batch(volatile uint32_t *s,uint32_t first,uint32_t *end)
{
    if (!end || !valid(s) || first<s[7] || first>=s[6] || s[6]==UINT32_MAX) return 0;
    uint32_t stop=s[6];
    /* All-or-nothing validation before changing ownership. No earlier READY
     * block may be skipped; preceding rows must already be host-owned.
     */
    for (uint32_t sequence=s[7];sequence<stop;++sequence) {
        volatile uint32_t *r=slot(s,sequence);
        if (r[0]!=sequence || r[2]!=PAIRED || r[1]!=(sequence<first?HOST:0u)) return 0;
    }
    for (uint32_t sequence=first;sequence<stop;++sequence) slot(s,sequence)[1]=HOST;
    barrier();
    *end=stop;
    return 1;
}

uint32_t rxcapt_stream_release_batch(volatile uint32_t *s,uint32_t end)
{
    if (!valid(s) || end<=s[7] || end>s[6]) return 0;
    for (uint32_t sequence=s[7];sequence<end;++sequence) {
        volatile uint32_t *r=slot(s,sequence);
        if (r[0]!=sequence || r[1]!=HOST || r[2]!=PAIRED) return 0;
    }
    for (uint32_t sequence=s[7];sequence<end;++sequence) {
        volatile uint32_t *r=slot(s,sequence);
        r[0]=FREE; r[1]=0; r[2]=0;
    }
    barrier();
    s[7]=end;
    barrier();
    return 1;
}

uint32_t rxcapt_stream_exchange_batch(volatile uint32_t *s,uint32_t end,uint32_t *claimed)
{
    if(!claimed || !valid(s) || end<s[7] || end>s[6] || s[6]==UINT32_MAX)return 0;
    uint32_t published=s[6],first=s[7];
    int ready_seen=0;
    /* Complete validation before any release: an invalid later row must not
     * free earlier USB buffers. HOST ownership forms one contiguous prefix;
     * remaining completed rows are READY, never active DMA or mixed flags. */
    for(uint32_t sequence=first;sequence<published;++sequence) {
        volatile uint32_t *r=slot(s,sequence);
        if(r[0]!=sequence || r[2]!=PAIRED || (r[1]!=HOST && r[1]!=0u))return 0;
        if(sequence<end) {if(r[1]!=HOST)return 0;}
        else if(!r[1])ready_seen=1;
        else if(ready_seen)return 0;
    }
    for(uint32_t sequence=first;sequence<end;++sequence) {
        volatile uint32_t *r=slot(s,sequence);
        r[0]=FREE;r[1]=0;r[2]=0;
    }
    for(uint32_t sequence=end;sequence<published;++sequence)slot(s,sequence)[1]=HOST;
    barrier();s[7]=end;barrier();*claimed=published;
    return 1;
}
