#include "usb_segment_profile.h"
struct stage {uint32_t count,max,hist[6];uint64_t total;};
static struct {uint32_t enabled,exchanges,released,claimed;struct stage stages[USB_PROFILE_STAGES];} profile;
static struct {
    uint32_t opened,completed,aborted,active;
    uint64_t origin;
    uint32_t rows[USB_REFILL_SAMPLES][8];
} refill;
int usb_segment_profile_enabled(void){return profile.enabled!=0;}
int usb_segment_profile_configure(uint32_t enabled)
{if(enabled>1)return 0;profile.enabled=enabled;return 1;}
void usb_segment_profile_reset(void)
{uint32_t enabled=profile.enabled;profile=(__typeof__(profile)){0};profile.enabled=enabled;
 refill=(__typeof__(refill)){0};}
void usb_segment_profile_record(unsigned stage,uint64_t start,uint64_t end)
{
    if(!profile.enabled || stage>=USB_PROFILE_STAGES)return;
    uint64_t delta=end-start;struct stage *s=&profile.stages[stage];
    ++s->count;s->total+=delta;
    if(delta>s->max)s->max=delta>UINT32_MAX?UINT32_MAX:(uint32_t)delta;
    const uint32_t edges[5]={10,25,50,100,250};unsigned i=0;
    while(i<5 && delta>edges[i])++i;
    ++s->hist[i];
}
void usb_segment_profile_exchange(uint32_t released,uint32_t claimed)
{if(profile.enabled){++profile.exchanges;profile.released+=released;profile.claimed+=claimed;}}
void usb_segment_profile_words(uint32_t out[USB_PROFILE_WORDS])
{
    for(unsigned i=0;i<USB_PROFILE_WORDS;++i)out[i]=0;
    out[0]=0x31525055u;out[1]=1;out[2]=profile.enabled;
    out[3]=profile.exchanges;out[4]=profile.released;out[5]=profile.claimed;
    for(unsigned i=0;i<USB_PROFILE_STAGES;++i) {
        const struct stage *s=&profile.stages[i];unsigned at=6+i*10;
        out[at]=s->count;out[at+1]=(uint32_t)s->total;out[at+2]=(uint32_t)(s->total>>32);out[at+3]=s->max;
        for(unsigned j=0;j<6;++j)out[at+4+j]=s->hist[j];
    }
}
static uint32_t refill_offset(uint64_t now)
{uint64_t delta=now-refill.origin;return delta>UINT32_MAX?UINT32_MAX:(uint32_t)delta;}
int usb_refill_active(void){return profile.enabled && refill.active;}
void usb_refill_begin(uint64_t now)
{
    if(!profile.enabled)return;
    if(refill.active)usb_refill_end(0,now);
    uint32_t *row=refill.rows[refill.opened%USB_REFILL_SAMPLES];
    for(unsigned i=0;i<8;++i)row[i]=0;
    row[0]=++refill.opened;refill.origin=now;refill.active=1;
}
void usb_refill_event(unsigned event,uint64_t now,uint32_t context)
{
    if(!profile.enabled || !refill.active || event>=USB_REFILL_EVENTS)return;
    uint32_t *row=refill.rows[(refill.opened-1u)%USB_REFILL_SAMPLES];
    uint32_t bit=1u<<event;
    if(row[1]&bit)return;
    row[1]|=bit;row[2u+event]=refill_offset(now);
    if(event==USB_REFILL_WORKER)row[7]=context;
}
void usb_refill_end(int successful,uint64_t now)
{
    if(!refill.active)return;
    uint32_t *row=refill.rows[(refill.opened-1u)%USB_REFILL_SAMPLES];
    row[1]|=successful?16u:32u;row[6]=refill_offset(now);
    if(successful)++refill.completed;else ++refill.aborted;
    refill.active=0;
}
void usb_refill_words(uint32_t out[USB_REFILL_WORDS])
{
    for(unsigned i=0;i<USB_REFILL_WORDS;++i)out[i]=0;
    out[0]=0x31524655u;out[1]=1;out[2]=profile.enabled;
    out[5]=refill.opened;out[6]=refill.completed;out[7]=refill.aborted;
    out[8]=refill.active;out[9]=refill.opened<USB_REFILL_SAMPLES?refill.opened:USB_REFILL_SAMPLES;
    uint32_t first=refill.opened-out[9];
    for(unsigned i=0;i<out[9];++i)
        for(unsigned j=0;j<8;++j)out[10u+i*8u+j]=refill.rows[(first+i)%USB_REFILL_SAMPLES][j];
}
