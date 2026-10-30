#include "rfad_rx_request.h"
#include <stddef.h>

_Static_assert(sizeof(struct rfad_rx_request_config)==36,"RX config ABI");
_Static_assert(sizeof(struct rfad_rx_request_plan)==128,"RX plan ABI");
_Static_assert(offsetof(struct rfad_rx_request_plan,event_words)==28,"event packet alignment");
_Static_assert(offsetof(struct rfad_rx_request_plan,rx_words)==68,"RX packet alignment");

int rfad_rx_request_plan(const struct rfad_rx_request_config *c,
                         struct rfad_rx_request_plan *out,
                         uint32_t cycle, uint32_t ssfn) {
    if (!c || !out || c->target_subframe>=10 || (c->mode!=1 && c->mode!=2) ||
        c->band_indicator>65535 || c->channel>65535 || c->bandwidth_index>5 ||
        c->gain>65535 || c->card>1 || c->offset>=30720 || !c->length ||
        c->length>30720-c->offset || cycle>65535 || ssfn>=10240) return -1;
    ssfn+=2;
    if(ssfn>=10240){ssfn-=10240;cycle=(cycle+1)&65535u;}
    out->advanced_cycle=cycle;
    out->advanced_ssfn=ssfn;
    out->selected_subframe=ssfn%10u;
    out->mode1_stop_required=0;
    out->mode1_end_cycle=0;
    out->mode1_end_ssfn=0;
    out->mode1_end_offset=0;
    for(unsigned i=0;i<10;i++)out->event_words[i]=0;
    for(unsigned i=0;i<15;i++)out->rx_words[i]=0;
    if(out->selected_subframe!=c->target_subframe)return 0;
    uint32_t time=cycle|(ssfn<<16);
    out->event_words[0]=c->mode|(1u<<16);
    out->event_words[1]=c->band_indicator|(c->channel<<16);
    out->event_words[2]=c->bandwidth_index;
    out->event_words[3]=c->card;
    out->event_words[4]=time;
    out->event_words[6]=c->offset;
    out->event_words[8]=c->length;
    out->rx_words[0]=c->card|((uint32_t)(c->mode==1)<<16);
    out->rx_words[1]=(uint32_t)(c->mode==2)|(c->gain<<16);
    unsigned index=c->mode==1?5:10;
    out->rx_words[index]=time;
    out->rx_words[index+2]=c->offset;
    out->rx_words[index+4]=c->length;
    if(c->mode==1){
        out->mode1_stop_required=1;
        uint32_t end=c->offset+c->length;
        if(end==30720){
            end=0;ssfn++;
            if(ssfn==10240){ssfn=0;cycle=(cycle+1)&65535u;}
        }
        out->mode1_end_cycle=cycle;
        out->mode1_end_ssfn=ssfn;
        out->mode1_end_offset=end;
    }
    return 1;
}
