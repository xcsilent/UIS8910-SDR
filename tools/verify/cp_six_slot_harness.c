#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "cp_capture_bridge.h"
#include "rxcapt_stream_batch.h"
#include "rxcapt_finite_abi.h"

int main(void) {
    uint32_t cp[30] = {0}, end;
    struct iq_usb_ring ring;
    struct cp_capture_bridge bridge;
    struct iq_usb_request req[6];
    cp[0] = 0x53545231u; cp[1] = 1; cp[2] = SDR_RX_OUTPUT_SLOTS;
    assert(SDR_RX_OUTPUT_SLOTS == 6u);
    for (unsigned i=0;i<6;i++) cp[9+3*i] = UINT32_MAX;
    assert(cp_capture_bridge_init(&bridge, &ring, 1) && ring.slots == 6);
    for (unsigned i=0;i<6;i++) { cp[9+3*i]=i; cp[11+3*i]=3; }
    cp[6]=6;
    assert(rxcapt_stream_exchange_batch(cp,0,&end) && end==6);
    assert(cp_capture_exchange_commit(&bridge,1,0,6));
    for (unsigned i=0;i<6;i++) {
        assert(iq_usb_take(&ring,&req[i]));
        assert(req[i].dma_address==0x80960000u+i*RXCAPT_FINITE_DATA_BYTES);
    }
    assert(iq_usb_complete(&ring,req[5].token,1));
    assert(cp_capture_release_begin(&bridge)==0);
    for (unsigned i=0;i<5;i++) assert(iq_usb_complete(&ring,req[i].token,1));
    assert(cp_capture_release_begin(&bridge)==6);
    assert(rxcapt_stream_exchange_batch(cp,6,&end) && end==6);
    assert(cp_capture_exchange_commit(&bridge,1,6,6));
    /* Sequence six must wrap to slot zero, not reserved scratch slot six. */
    cp[9]=6; cp[11]=3; cp[6]=7;
    assert(rxcapt_stream_exchange_batch(cp,6,&end) && end==7);
    assert(cp_capture_exchange_commit(&bridge,1,6,7));
    assert(iq_usb_take(&ring,&req[0]) && req[0].dma_address==0x80960000u);
    assert(iq_usb_complete(&ring,req[0].token,1));
    assert(cp_capture_release_begin(&bridge)==7);
    assert(rxcapt_stream_exchange_batch(cp,7,&end) && end==7);
    assert(cp_capture_exchange_commit(&bridge,1,7,7));
    puts("six-slot ordered bridge and wrap passed");
    return 0;
}
