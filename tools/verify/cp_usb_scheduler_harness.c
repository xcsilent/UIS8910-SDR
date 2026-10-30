#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../../firmware/sdr_receiver/cp_usb_scheduler.h"
int main(void)
{
    struct cp_usb_scheduler s={0},before;
    uint32_t words[30];cp_usb_scheduler_words(&s,words);assert(words[2]==250 && !words[3]);
    assert(cp_usb_scheduler_wait(&s,0,1,0,0)==250);cp_usb_scheduler_slept(&s,600);
    assert(cp_usb_scheduler_configure(&s,50,40));before=s;
    assert(!cp_usb_scheduler_configure(&s,0,40) && !memcmp(&s,&before,sizeof(s)));
    assert(!cp_usb_scheduler_configure(&s,24,0) && !cp_usb_scheduler_configure(&s,1001,0));
    assert(!cp_usb_scheduler_configure(&s,50,51));
    cp_usb_scheduler_reset(&s);assert(s.wait_us==50 && s.burst_us==40 && !s.waits);
    /* A frozen microsecond clock still yields after eight polls. */
    for(unsigned i=0;i<8;++i)assert(!cp_usb_scheduler_wait(&s,0,1,17,100));
    assert(cp_usb_scheduler_wait(&s,0,1,17,100)==50);cp_usb_scheduler_slept(&s,75);
    assert(s.fast_polls==8 && s.exhaustions==1 && s.sleeps==1);
    /* Real elapsed budget can force yield before the iteration limit. */
    assert(!cp_usb_scheduler_wait(&s,0,1,17,200));
    assert(cp_usb_scheduler_wait(&s,0,1,17,240)==50);cp_usb_scheduler_slept(&s,300);
    assert(s.exhaustions==2);
    assert(!cp_usb_scheduler_wait(&s,0,1,17,300));
    assert(!cp_usb_scheduler_wait(&s,1,1,17,0));assert(!s.burst_polls);
    assert(!cp_usb_scheduler_wait(&s,0,0,17,0));
    assert(cp_usb_scheduler_wait(&s,0,1,0,400)==50);cp_usb_scheduler_slept(&s,1200);
    cp_usb_scheduler_observe(&s,17,16,1000);
    cp_usb_scheduler_observe(&s,17,16,1010); /* no repeated queue timestamp */
    cp_usb_scheduler_observe(&s,18,17,1060); /* complete old and queue next */
    cp_usb_scheduler_observe(&s,0,18,1500);
    assert(s.acks==2 && s.ack_us==500 && s.max_ack_us==440);
    assert(s.ack_hist[1]==1 && s.ack_hist[3]==1);
    cp_usb_scheduler_words(&s,words);
    assert(words[0]==0x31484353 && words[1]==1 && words[2]==50 && words[3]==40 && words[29]==8);
    uint32_t sleeps=0,acks=0;for(unsigned i=0;i<6;++i){sleeps+=words[17+i];acks+=words[23+i];}
    assert(sleeps==s.sleeps && acks==s.acks && words[10]==1575 && words[12]==1200);
    cp_usb_scheduler_reset(&s);assert(!s.acks && !s.sleeps && s.wait_us==50 && s.burst_us==40);
    assert(cp_usb_scheduler_configure(&s,250,0));
    for(unsigned i=0;i<20;++i)assert(cp_usb_scheduler_wait(&s,0,1,17,i)==250);
    /* Explicit settings survive bandwidth changes and per-session reset. */
    assert(cp_usb_scheduler_begin(&s,5) && s.manual_override && s.wait_us==250 && !s.waits);
    assert(cp_usb_scheduler_configure(&s,75,20));
    assert(cp_usb_scheduler_begin(&s,0) && s.manual_override && s.wait_us==75 && s.burst_us==20);
    before=s;assert(!cp_usb_scheduler_begin(&s,6) && !memcmp(&s,&before,sizeof(s)));
    cp_usb_scheduler_automatic(&s);assert(!s.manual_override && s.wait_us==250 && !s.burst_us);
    for(unsigned bw=0;bw<6;++bw){
        assert(cp_usb_scheduler_begin(&s,bw) && s.bandwidth_index==bw);
        assert(s.wait_us==(bw>=2?100u:250u) && !s.burst_us && !s.manual_override);
    }
    cp_usb_scheduler_reset(&s);assert(s.wait_us==100 && s.bandwidth_index==5 && !s.manual_override);
    assert(cp_usb_scheduler_begin(&s,0) && s.wait_us==250);
    puts("scheduler passed: default, time/poll bounds, notification, no-wait, safe configuration, latency and per-session counters");
    return 0;
}
