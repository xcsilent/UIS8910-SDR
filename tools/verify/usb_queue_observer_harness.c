#include <assert.h>
#include <stdio.h>
#include "../../firmware/sdr_receiver/usb_queue_observer.h"
int main(void)
{
    struct usb_queue_observer q={0};
    enum usb_queue_request_state a=USB_Q_IDLE,b=USB_Q_IDLE;
    usb_queue_begin(&a);usb_queue_complete(&q,&a,1,0,10);usb_queue_submit_result(&q,&a,1,20);
    assert(q.synchronous==1 && q.accepted==0 && q.empty_completions==0 && a==USB_Q_IDLE);
    usb_queue_begin(&a);usb_queue_submit_result(&q,&a,0,20);assert(q.rejected==1 && !q.accepted);
    usb_queue_begin(&a);usb_queue_submit_result(&q,&a,1,20);
    usb_queue_begin(&b);usb_queue_submit_result(&q,&b,1,20);assert(q.accepted==2);
    usb_queue_complete(&q,&a,1,0,30);assert(q.accepted==1 && q.completions==1 && !q.empty_completions);
    usb_queue_complete(&q,&b,1,0,40);assert(!q.accepted && q.completions==2 && q.empty_completions==1);
    usb_queue_begin(&a);usb_queue_submit_result(&q,&a,1,90);assert(q.gap_count==1 && q.gap_total_us==50 && q.gap_max_us==50);
    usb_queue_complete(&q,&a,0,1,100);
    assert(!q.accepted && q.cancelled==1 && q.empty_completions==1);
    usb_queue_complete(&q,&a,1,0,110);assert(!q.accepted && q.completions==2);
    puts("queue observer: synchronous, rejection, queued completions, cancellation and duplicate callback passed");
    return 0;
}
