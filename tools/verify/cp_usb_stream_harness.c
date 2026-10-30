#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "cp_usb_stream.h"
#include "rxcapt_stream_batch.h"
#include "rxcapt_finite_abi.h"
#define TEST_SLOTS SDR_RX_OUTPUT_SLOTS
#define TEST_BYTES RXCAPT_FINITE_DATA_BYTES

#define GEN 0x52550001u
static uint32_t lines[16] __attribute__((aligned(32)));
static uint32_t progress[8] __attribute__((aligned(32)));
static uint32_t exported[32] __attribute__((aligned(32)));
static uint32_t cp[30],cp_last,phase,cp_error,cp_stop,now;
static struct cp_stream_mailbox mailbox;
static struct cp_usb_stream stream;
static struct sdr_udc udc;
static struct sdr_usb_ep ep={0x86,0,512};
struct fake_xfer { struct sdr_usb_xfer xfer; uint32_t private_tail[4]; };
static struct fake_xfer transfers[64];
static struct sdr_usb_xfer *queued[64];
static unsigned allocated,freed,queued_count,cancels,notifications,depth,cleans,invalidated,mutate,torn;
static int reject_submit;

static uint32_t *row(uint32_t sequence) { return cp+9+(sequence%TEST_SLOTS)*3; }
static uint32_t enter(void *context) { (void)context; return depth++; }
static void leave(void *context,uint32_t key) { (void)context; assert(depth==key+1); depth=key; }
static void barrier(void *context) { (void)context; }
static void clean(void *context,const volatile void *address,uint32_t bytes)
{
    (void)context;
    assert(address==lines && bytes==32); /* never clean CP response or payload */
    ++cleans;
}
static void invalidate(void *context,const volatile void *address,uint32_t bytes)
{
    (void)context;
    assert((address==lines+8 || address==progress || address==exported) && (bytes==32 || bytes==128));
    invalidated+=bytes;
    if (mutate && address==exported) { ++exported[4]; ++torn; }
}
static int prepare(void *context,uint32_t address,uint32_t bytes)
{
    (void)context;
    assert(!depth && address>=0x80960000 && address+bytes<=0x80960000u+TEST_SLOTS*TEST_BYTES && bytes==TEST_BYTES);
    return 1;
}
static void notify(void *context) { (void)context; ++notifications; }
static struct sdr_usb_xfer *allocate(struct sdr_udc *controller)
{
    assert(controller==&udc && allocated<64);
    struct fake_xfer *request=&transfers[allocated++];
    request->private_tail[0]=0x12345678;
    return &request->xfer;
}
static void free_xfer(struct sdr_udc *controller,struct sdr_usb_xfer *xfer)
{
    assert(controller==&udc && ((struct fake_xfer *)xfer)->private_tail[0]==0x12345678);
    ++freed;
}
static int enqueue(struct sdr_udc *controller,struct sdr_usb_ep *endpoint,struct sdr_usb_xfer *xfer)
{
    assert(controller==&udc && endpoint==&ep && queued_count<64);
    assert(xfer->uncached && !xfer->zlp && xfer->length==TEST_BYTES);
    if(reject_submit) return -2;
    queued[queued_count++]=xfer;
    return 0;
}
static void dequeue_all(struct sdr_udc *controller,struct sdr_usb_ep *endpoint)
{
    assert(controller==&udc && endpoint==&ep && phase>=30 && cp_stop);
    ++cancels; /* callbacks remain delayed until test explicitly completes them */
}
static void setup(void)
{
    memset(lines,0,sizeof(lines)); memset(cp,0,sizeof(cp)); memset(&stream,0,sizeof(stream));
    memset(&udc,0,sizeof(udc)); memset(transfers,0,sizeof(transfers));
    allocated=freed=queued_count=cancels=notifications=depth=cleans=invalidated=mutate=torn=0;
    cp_last=cp_error=cp_stop=now=0; phase=27;
    reject_submit=0;
    cp[0]=0x53545231; cp[1]=1; cp[2]=TEST_SLOTS;
    for(unsigned i=0;i<TEST_SLOTS;++i) row(i)[0]=UINT32_MAX;
    udc.ops.xfer_alloc=allocate; udc.ops.xfer_free=free_xfer;
    udc.ops.enqueue=enqueue; udc.ops.dequeue_all=dequeue_all;
    assert(cp_stream_mailbox_init(&mailbox,lines,GEN,(struct cp_mailbox_cache){0,clean,invalidate,barrier}));
}
static struct cp_capture_snapshot snapshot(void)
{
    return (struct cp_capture_snapshot){GEN,phase,cp_error,cp[6],cp[7],cp_stop,phase>=30};
}
static void open_stream(void)
{
    assert(cp_usb_stream_open(&stream,&mailbox,&udc,&ep,
        (struct iq_udc_platform){0,enter,leave,prepare,notify},snapshot(),now,100));
}
static void produce(uint32_t count)
{
    uint32_t first=cp[6];
    assert(first+count-cp[7]<=TEST_SLOTS && !cp_stop);
    for(uint32_t i=first;i<first+count;++i) {
        assert(row(i)[0]==UINT32_MAX);
        row(i)[0]=i; row(i)[1]=0; row(i)[2]=3;
    }
    cp[6]=first+count;
}
static void cp_poll(void)
{
    if (!lines[2] || lines[2]==cp_last) return;
    assert(lines[0]==0x52585331 && lines[1]==GEN && lines[2]==cp_last+1);
    assert(lines[4]==cp_last && lines[6]==~lines[2] && lines[7]==lines[2]);
    uint32_t operation=lines[3],block=lines[5],end=block,result=0;
    if(operation==11) result=rxcapt_stream_claim_batch(cp,block,&end);
    else if(operation==12) result=rxcapt_stream_release_batch(cp,block);
    else if(operation==14) result=rxcapt_stream_exchange_batch(cp,block,&end);
    else if(operation==7) { cp_stop=1; result=1; }
    assert(result);
    cp_last=lines[2];
    uint32_t reply[8]={0x52585331,GEN,cp_last,operation,0,block,end,cp_last};
    memcpy(lines+8,reply,sizeof(reply));
}
static void tick(void)
{
    struct cp_capture_snapshot value=snapshot();
    cp_usb_stream_tick(&stream,&value,now++);
}
static void finish(unsigned index,int error,uint32_t bytes)
{
    struct sdr_usb_xfer *x=queued[index];
    x->status=error; x->actual=bytes; x->complete(&ep,x);
}

int main(void)
{
    setup();
    assert(cp_usb_stream_prepare(&stream,&mailbox,&udc,&ep,
        (struct iq_udc_platform){0,enter,leave,prepare,notify},100));
    assert(allocated==TEST_SLOTS && stream.phase==CP_USB_PREPARED);
    tick(); assert(!queued_count && !mailbox.pending);
    struct cp_capture_snapshot wrong=snapshot(); wrong.generation--;
    assert(!cp_usb_stream_begin(&stream,wrong,now));
    assert(allocated==TEST_SLOTS && !freed && stream.phase==CP_USB_PREPARED);
    cp_usb_stream_stop(&stream); /* stop during RF initialization survives begin */
    assert(cp_usb_stream_begin(&stream,snapshot(),now) && allocated==TEST_SLOTS);
    tick(); assert(mailbox.pending && mailbox.operation==7);
    cp_poll(); phase=30; tick();
    assert(stream.phase==CP_USB_DRAINED && freed==TEST_SLOTS);

    setup();
    assert(cp_usb_stream_prepare(&stream,&mailbox,&udc,&ep,
        (struct iq_udc_platform){0,enter,leave,prepare,notify},100));
    assert(cp_usb_stream_unprepare(&stream) && freed==TEST_SLOTS && stream.phase==CP_USB_CLOSED);

    setup(); open_stream(); produce(3);
    tick(); assert(mailbox.pending && mailbox.operation==11 && !queued_count);
    tick(); assert(!queued_count && cp_last==0); /* nonblocking delayed CP command */
    cp_poll(); tick(); assert(queued_count==3 && cp[7]==0);
    finish(2,0,TEST_BYTES); tick(); assert(!mailbox.pending && cp[7]==0);
    finish(0,0,TEST_BYTES); tick(); assert(mailbox.operation==12 && mailbox.pending);
    tick(); assert(cp[7]==0 && !cp_capture_claim_credit(&stream.bridge));
    cp_poll(); tick(); assert(cp[7]==1 && stream.bridge.released==1);
    finish(1,0,TEST_BYTES); tick(); cp_poll(); tick();
    assert(cp[7]==3 && stream.bridge.released==3);
    cp_usb_stream_stop(&stream); tick(); assert(mailbox.operation==7 && mailbox.pending);
    cp_poll(); tick(); assert(stream.stop_accepted && stream.phase==CP_USB_STOPPING && freed==0);
    phase=30; tick(); assert(stream.phase==CP_USB_DRAINED && freed==TEST_SLOTS && cancels==0);
    assert(stream.ring.stats.completed_bytes==3u*TEST_BYTES && stream.commands==4);

    setup(); open_stream(); produce(2); tick(); cp_poll(); tick();
    finish(0,-5,16); tick();
    assert(stream.phase==CP_USB_FAULT && !cancels && !freed); /* CP still active */
    assert(mailbox.pending && mailbox.operation==7); /* failure actively stops producer */
    cp_poll(); tick(); assert(stream.stop_accepted && !cancels && !freed);
    phase=30; tick(); assert(cancels==1 && !freed);
    finish(1,-125,0); tick(); assert(freed==TEST_SLOTS && stream.usb.opened==0);
    assert(cp[7]==0); /* failure never fabricates CP release */

    setup(); open_stream(); produce(1); tick(); cp_poll();
    reject_submit=1; tick();
    assert(stream.phase==CP_USB_FAULT && stream.usb.rejected==1 && !queued_count);
    assert(!freed && !cancels && cp[7]==0);
    tick(); assert(mailbox.pending && mailbox.operation==7);
    cp_poll(); tick(); assert(stream.stop_accepted && !freed && !cancels);
    phase=30; tick(); assert(cancels==1 && freed==TEST_SLOTS && cp[7]==0);

    setup(); open_stream(); produce(1); tick();
    now=1001; tick(); assert(stream.phase==CP_USB_FAULT && mailbox.pending && !cancels);
    assert(!cp_stream_mailbox_begin(&mailbox,7,0,now,1000));
    cp_poll(); tick(); assert(mailbox.completed==1 && stream.phase==CP_USB_FAULT);
    assert(!cp_stream_mailbox_begin(&mailbox,7,0,now,1000)); /* timeout was a session fault, even after late reply */
    cp_stop=1; phase=30; tick(); assert(cancels==1 && freed==TEST_SLOTS);

    setup(); open_stream(); produce(1); tick();
    lines[8]=0x52585331;lines[9]=GEN;lines[10]=1;lines[11]=4;lines[12]=0xc16;lines[15]=1;
    tick(); assert(stream.phase==CP_USB_FAULT && mailbox.fault && !mailbox.pending && mailbox.completed==0);
    assert(!cp_stream_mailbox_begin(&mailbox,11,0,now,1000));

    setup(); open_stream(); produce(1); tick();
    lines[8]=0x52585331;lines[9]=GEN-1;lines[10]=1;lines[11]=11;lines[15]=1;
    tick(); assert(mailbox.pending && stream.phase==CP_USB_RUNNING); /* ignore stale generation */
    now=101; cp_poll(); tick(); assert(stream.phase==CP_USB_STOPPING && mailbox.operation==7);
    cp_poll(); tick(); finish(0,0,TEST_BYTES); tick(); cp_poll(); phase=30; tick();
    assert(stream.phase==CP_USB_DRAINED && stream.stop_accepted);

    setup();
    memset(progress,0,sizeof(progress)); memset(exported,0,sizeof(exported));
    progress[0]=0x54524d31;progress[1]=GEN;progress[2]=4;progress[3]=27;
    exported[0]=0x53545231;exported[1]=1;exported[2]=TEST_SLOTS;exported[6]=3;
    struct cp_capture_snapshot value;
    struct cp_mailbox_cache cache={0,clean,invalidate,barrier};
    assert(cp_capture_snapshot_read(progress,exported,GEN,cache,&value));
    assert(value.published==3 && value.dma_idle==0 && invalidated==128);
    mutate=1;
    assert(!cp_capture_snapshot_read(progress,exported,GEN,cache,&value) && torn>0);
    mutate=0;progress[2]=5;
    assert(!cp_capture_snapshot_read(progress,exported,GEN,cache,&value));
    progress[2]=6;progress[3]=30;exported[3]=1;exported[10]=1;
    assert(cp_capture_snapshot_read(progress,exported,GEN,cache,&value) && !value.dma_idle);
    exported[10]=0;
    assert(cp_capture_snapshot_read(progress,exported,GEN,cache,&value) && value.dma_idle);
    assert(!cp_capture_snapshot_read(progress,exported,GEN+1,cache,&value));

    setup();
    assert(cp_usb_stream_open(&stream,&mailbox,&udc,&ep,
        (struct iq_udc_platform){0,enter,leave,prepare,notify},snapshot(),now,0));
    now=210000;tick();assert(stream.phase==CP_USB_RUNNING && !stream.stop_requested);
    cp_usb_stream_stop(&stream);tick();cp_poll();phase=30;tick();
    assert(stream.phase==CP_USB_DRAINED && allocated==freed);
    puts("CP USB stream passed: explicit-stop mode survives210s and drains, preallocation/early stop, async AP mailbox/bridge/UDC, ordered release, fault STOP, late replies, metadata-only snapshots; payload never mapped");
    return 0;
}
