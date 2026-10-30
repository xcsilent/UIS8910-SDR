#ifndef SDR_UDC_8910_H
#define SDR_UDC_8910_H

#include <stddef.h>
#include <stdbool.h>
#include <stdint.h>

/* Public ABI recovered from the 720U SDK DWARF and compared against the
 * installed Fine RFv6 AP. Driver-private transfer fields follow this prefix:
 * requests MUST come from xfer_alloc, never sizeof(struct sdr_usb_xfer).
 */
struct sdr_udc;
struct sdr_usb_ep { uint8_t address, attributes; uint16_t mps; };
struct sdr_usb_xfer {
    void *buf;
    uint32_t length, actual;
    int status;
    uint8_t zlp, uncached;
    void *param;
    void (*complete)(struct sdr_usb_ep *, struct sdr_usb_xfer *);
};
struct sdr_udc_ops {
    void (*start)(struct sdr_udc *);
    void (*stop)(struct sdr_udc *);
    bool (*remote_wakeup)(struct sdr_udc *);
    int (*enqueue)(struct sdr_udc *, struct sdr_usb_ep *, struct sdr_usb_xfer *);
    void (*dequeue)(struct sdr_udc *, struct sdr_usb_ep *, struct sdr_usb_xfer *);
    void (*dequeue_all)(struct sdr_udc *, struct sdr_usb_ep *);
    struct sdr_usb_ep *(*ep_alloc)(struct sdr_udc *, void *);
    void (*ep_free)(struct sdr_udc *, struct sdr_usb_ep *);
    int (*ep_enable)(struct sdr_udc *, struct sdr_usb_ep *);
    void (*ep_disable)(struct sdr_udc *, struct sdr_usb_ep *);
    void (*ep_stall)(struct sdr_udc *, struct sdr_usb_ep *, bool);
    struct sdr_usb_xfer *(*xfer_alloc)(struct sdr_udc *);
    void (*xfer_free)(struct sdr_udc *, struct sdr_usb_xfer *);
    void (*gdb_poll)(struct sdr_udc *);
};
struct sdr_udc {
    int speed, feature;
    void (*platform_ops[6])(void);
    struct sdr_udc_ops ops;
    uintptr_t platform_priv, controller_priv;
    struct sdr_usb_ep *ep0;
};

#if UINTPTR_MAX == UINT32_MAX
_Static_assert(sizeof(int) == 4, "8910 int ABI");
_Static_assert(sizeof(struct sdr_usb_xfer) == 28, "8910 xfer prefix ABI");
_Static_assert(offsetof(struct sdr_usb_xfer, uncached) == 17, "8910 cache flag ABI");
_Static_assert(offsetof(struct sdr_usb_xfer, param) == 20, "8910 parameter ABI");
_Static_assert(offsetof(struct sdr_usb_xfer, complete) == 24, "8910 completion ABI");
_Static_assert(offsetof(struct sdr_udc, ops.enqueue) == 44, "8910 enqueue ABI");
_Static_assert(offsetof(struct sdr_udc, controller_priv) == 92, "8910 private ABI");
_Static_assert(sizeof(struct sdr_udc) == 100, "8910 controller ABI");
#endif

#endif
