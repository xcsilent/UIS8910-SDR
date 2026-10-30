#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "iot_os.h"
#include "osi_api.h"
#include "debug_shared.h"
#include "iq_udc_adapter.h"
#include "raw_usb_function.h"
#include "udc_bindings.h"

#define BUFFER_BYTES (256u*1024u)
#define OS_VENDOR_CODE 0x5au

struct usb_setup { uint8_t type, request; uint16_t value, index, length; } __attribute__((packed));
struct usb_ep_descriptor {
    uint8_t length, type, address, attributes;
    uint16_t mps;
    uint8_t interval;
} __attribute__((packed));
struct usb_function;
struct usb_function_ops {
    uint32_t (*fill)(struct usb_function *, void *, uint32_t);
    int (*bind)(struct usb_function *, void *, struct sdr_udc *);
    void (*unbind)(struct usb_function *);
    void (*destroy)(struct usb_function *);
    int (*setup)(struct usb_function *, struct usb_setup *);
    int (*set_alt)(struct usb_function *, uint8_t, uint8_t);
    void (*disable)(struct usb_function *);
};
struct usb_function {
    uint32_t name;
    struct usb_function_ops ops;
    struct usb_function *next;
    struct usb_function **previous;
    void *composite;
    struct sdr_udc *udc;
};
struct composite_control { struct sdr_usb_xfer *xfer; uint8_t *buffer; uint32_t capacity; };
struct raw_function {
    struct usb_function function;
    uint8_t interface_desc[9];
    struct usb_ep_descriptor ep_desc;
    struct sdr_usb_ep *ep;
    uint32_t interface_number, attached, enabled;
};
_Static_assert(sizeof(struct usb_setup) == 8, "USB setup packet");
_Static_assert(sizeof(struct usb_ep_descriptor) == 7, "USB endpoint descriptor");
_Static_assert(sizeof(struct usb_function) == 48, "720U composite function ABI");
_Static_assert(offsetof(struct usb_function, composite) == 40, "720U composite pointer ABI");

static struct raw_function raw;
static struct iq_usb_ring ring;
static struct iq_udc_adapter adapter;
static uint8_t buffer[BUFFER_BYTES] __attribute__((aligned(32)));
static osiSemaphore_t *wake;
static uint32_t stats[SDR_RAW_STATS_WORDS];
static uint32_t start_requested, stop_requested, duration_ms, block_bytes, slot_count;
static uint32_t epoch;
#ifdef DBG_ENABLE_BW0_USB
static uint32_t capture_owned;
static void (*capture_stop)(void *);
static void *capture_context;
#endif
static int (*original_setup)(void *, struct usb_setup *);

static uint32_t enter(void *context) { (void)context; return osiEnterCritical(); }
static void leave(void *context, uint32_t key) { (void)context; osiExitCritical(key); }
static void notify(void *context) { (void)context; if (wake) osiSemaphoreRelease(wake); }
static int prepare(void *context, uint32_t address, uint32_t size)
{
    (void)context;
    /* Fixed AP buffer was cleaned once. Never clean it in the send path.
     * This callback is NOT suitable for arbitrary future CP capture buffers.
     */
    if (address < (uint32_t)buffer || size > BUFFER_BYTES ||
        address-(uint32_t)buffer > BUFFER_BYTES-size) return 0;
    dbg_cache_barrier();
    return 1;
}

static int assign_interface(void *composite, struct usb_function *function)
{
    return ((int (*)(void *, struct usb_function *))SDR_ADDR_COPS_ASSIGN_INTERFACE)(composite, function);
}
static int reply_control(void *composite, const struct usb_setup *setup,
                          const void *data, uint32_t length)
{
    struct composite_control *ctrl = ((struct composite_control *(*)(void *))SDR_ADDR_COPS_GET_CTRL)(composite);
    struct sdr_udc *udc = raw.function.udc;
    if (!ctrl || !ctrl->xfer || !ctrl->buffer || !udc || !udc->ep0) return -1;
    if (length > setup->length) length = setup->length;
    if (length > ctrl->capacity) return -1;
    if (length) memcpy(ctrl->buffer, data, length);
    struct sdr_usb_xfer *x = ctrl->xfer;
    x->buf = ctrl->buffer;
    x->length = length;
    x->actual = 0;
    x->status = 0;
    x->zlp = length < setup->length;
    x->uncached = 0; /* CPU-produced control reply: normal driver clean. */
    x->param = composite;
    x->complete = 0;
    return udc->ops.enqueue(udc, udc->ep0, x);
}
static void put16(uint8_t *p, uint16_t n) { p[0] = n; p[1] = n >> 8; }
static void put32(uint8_t *p, uint32_t n) { dbg_put32(p, n); }

static int windows_setup(void *composite, struct usb_setup *setup)
{
    static const uint8_t os_string[18] = {18,3,'M',0,'S',0,'F',0,'T',0,'1',0,'0',0,'0',0,OS_VENDOR_CODE,0};
    if (setup->type == 0x80u && setup->request == 6u && setup->value == 0x03eeu)
        return reply_control(composite, setup, os_string, sizeof(os_string));
    if ((setup->type == 0xc0u || setup->type == 0xc1u) && setup->request == OS_VENDOR_CODE) {
        if (setup->index == 4u && setup->value == 0u) {
            uint8_t compatible[40] = {0};
            put32(compatible, sizeof(compatible));
            put16(compatible+4, 0x0100);
            put16(compatible+6, 4);
            compatible[8] = 1;
            compatible[16] = raw.interface_number;
            compatible[17] = 1;
            memcpy(compatible+18, "WINUSB", 6);
            return reply_control(composite, setup, compatible, sizeof(compatible));
        }
        if (setup->index == 5u && setup->value == raw.interface_number) {
            static const char name[] = "DeviceInterfaceGUID";
            static const char guid[] = SDR_RAW_GUID;
            uint8_t properties[142] = {0};
            put32(properties, sizeof(properties));
            put16(properties+4, 0x0100);
            put16(properties+6, 5);
            put16(properties+8, 1);
            put32(properties+10, 132);
            put32(properties+14, 1); /* REG_SZ */
            put16(properties+18, sizeof(name)*2u);
            for (unsigned i=0; i<sizeof(name); ++i) properties[20+i*2u] = name[i];
            put32(properties+60, sizeof(guid)*2u);
            for (unsigned i=0; i<sizeof(guid); ++i) properties[64+i*2u] = guid[i];
            return reply_control(composite, setup, properties, sizeof(properties));
        }
        return -1;
    }
    return original_setup ? original_setup(composite, setup) : -1;
}

static uint32_t fill(struct usb_function *f, void *destination, uint32_t available)
{
    struct raw_function *r = (struct raw_function *)f;
    uint8_t descriptors[16];
    r->ep_desc.mps = f->udc->speed > 2 ? 512u : 64u;
    memcpy(descriptors, r->interface_desc, 9);
    memcpy(descriptors+9, &r->ep_desc, 7);
    if (available > sizeof(descriptors)) available = sizeof(descriptors);
    if (destination && available) memcpy(destination, descriptors, available);
    return available;
}
static int bind(struct usb_function *f, void *composite, struct sdr_udc *udc)
{
    struct raw_function *r = (struct raw_function *)f;
#ifdef DBG_ENABLE_BW0_USB
    if(capture_owned) return -1;
#endif
    r->ep = udc->ops.ep_alloc(udc, &r->ep_desc);
    if (!r->ep) return -1;
    int number = assign_interface(composite, f);
    if (number < 0) {
        udc->ops.ep_free(udc, r->ep);
        r->ep = 0;
        return -1;
    }
    r->interface_number = (uint32_t)number;
    r->interface_desc[2] = number;
    r->ep_desc.address = r->ep->address;
    r->attached = 1;
    return 0;
}
static void disable(struct usb_function *f)
{
    struct raw_function *r = (struct raw_function *)f;
    uint32_t key = osiEnterCritical();
    r->enabled = 0;
    stop_requested = 1;
    osiExitCritical(key);
    if (r->ep) f->udc->ops.ep_disable(f->udc, r->ep);
#ifdef DBG_ENABLE_BW0_USB
    if(capture_owned && capture_stop) capture_stop(capture_context);
#endif
    notify(0);
}
static void unbind(struct usb_function *f)
{
    struct raw_function *r = (struct raw_function *)f;
    disable(f);
    r->attached = 0;
#ifdef DBG_ENABLE_BW0_USB
    if(capture_owned) return;
#endif
    /* Endpoint disable cancels its requests. Do not free a live request/ring.
     * Normal operation retains the function across stop/start and reconnect.
     */
    if (adapter.opened && !iq_udc_close(&adapter)) return;
    if (r->ep) f->udc->ops.ep_free(f->udc, r->ep);
    r->ep = 0;
}
static void destroy(struct usb_function *f) { (void)f; }
static int function_setup(struct usb_function *f, struct usb_setup *request)
{ (void)f; (void)request; return -1; }
static int set_alt(struct usb_function *f, uint8_t interface_number, uint8_t alternate)
{
    struct raw_function *r = (struct raw_function *)f;
    if (!r->ep || interface_number != r->interface_number || alternate) return -1;
    int result = f->udc->ops.ep_enable(f->udc, r->ep);
    if (result >= 0) r->enabled = 1;
    notify(0);
    return result;
}

static void update_stats(uint32_t state, uint32_t error, uint64_t active_us,
                          uint32_t elapsed_ms, uint32_t wakeups)
{
    uint32_t key = osiEnterCritical();
    stats[3] = raw.interface_number;
    stats[4] = raw.ep ? raw.ep->address : 0;
    stats[5] = raw.enabled;
    stats[6] = state;
    stats[7] = error;
    stats[8] = epoch;
    stats[9] = duration_ms;
    stats[10] = elapsed_ms;
    stats[11] = block_bytes;
    stats[12] = slot_count;
    stats[13] = ring.stats.submitted;
    stats[14] = ring.stats.completed;
    stats[15] = ring.stats.usb_failures;
    stats[16] = adapter.rejected;
    stats[17] = adapter.callback_errors;
    stats[18] = (uint32_t)ring.stats.completed_bytes;
    stats[19] = (uint32_t)(ring.stats.completed_bytes >> 32);
    stats[20] = (uint32_t)active_us;
    stats[21] = (uint32_t)(active_us >> 32);
    stats[22] = wakeups;
    stats[23] = 1; /* Fixed AP buffer benchmark, NOT RF or capture DMA. */
    osiExitCritical(key);
}
static void worker(void *argument)
{
    (void)argument;
    for (;;) {
        osiSemaphoreAcquire(wake);
        uint32_t key = osiEnterCritical();
        uint32_t start = start_requested;
        start_requested = 0;
        osiExitCritical(key);
        if (!start) continue;
        uint32_t error = 0, wakeups = 0;
        uint64_t active_us = 0;
        int64_t begun = osiUpTimeUS();
        if (!raw.enabled || adapter.opened ||
            !iq_usb_init(&ring, (uint32_t)buffer, BUFFER_BYTES, block_bytes, slot_count, epoch) ||
            !iq_udc_open(&adapter, &ring, raw.function.udc, raw.ep,
                         (struct iq_udc_platform){0,enter,leave,prepare,notify})) {
            update_stats(4, DBG_NOT_READY, 0, 0, 0);
            continue;
        }
        uint32_t stopping = 0, cancel_sent = 0;
        int64_t drain_started = 0;
        for (;;) {
            int64_t active_start = osiUpTimeUS();
            uint32_t elapsed = (uint32_t)((active_start-begun)/1000);
            key = osiEnterCritical();
            if (!stopping && (stop_requested || !raw.enabled || adapter.terminal_error || elapsed >= duration_ms)) {
                stopping = 1;
                drain_started = active_start;
                if (!raw.enabled || adapter.terminal_error) error = DBG_ACCESS;
            }
            if (!stopping) {
                for (unsigned i=0; i<ring.slots; ++i) {
                    if (ring.slot[i].state != IQ_FREE) continue;
                    struct iq_usb_request request;
                    if (iq_capture_acquire(&ring, &request))
                        iq_capture_publish(&ring, request.token, request.bytes);
                }
            }
            osiExitCritical(key);
            iq_udc_pump(&adapter, slot_count);
            if (stopping && !cancel_sent && (error || active_start-drain_started > 1000000)) {
                iq_udc_cancel(&adapter);
                cancel_sent = 1;
                if (!error) error = DBG_TIMEOUT;
            }
            active_us += (uint64_t)(osiUpTimeUS()-active_start);
            if (stopping && iq_udc_close(&adapter)) {
                update_stats(error ? 4 : 3, error, active_us, elapsed, wakeups);
                break;
            }
            if (stopping && active_start-drain_started > 2000000) {
                /* Keep descriptors and buffers owned; no unsafe recovery. */
                update_stats(4, DBG_TIMEOUT, active_us, elapsed, wakeups);
                break;
            }
            update_stats(stopping ? 2 : 1, error, active_us, elapsed, wakeups);
            osiSemaphoreTryAcquire(wake, 1);
            ++wakeups;
        }
    }
}

int sdr_raw_install(void)
{
    stats[0] = 0x31525153u;
    stats[1] = SDR_RAW_ABI;
    stats[2] = DBG_NOT_READY;
    stats[3] = UINT32_MAX;
    uint32_t device = *(volatile uint32_t *)SDR_USB_GLOBAL;
    if (device < 0x80989f60u || device > 0x80ffffb8u || (device&3u)) return -1;
    struct sdr_udc *udc = *(struct sdr_udc **)(device+28u);
    void *composite = *(void **)(device+32u);
    if (!udc || !composite || (uintptr_t)udc->ops.enqueue != SDR_ADDR_PRV_DWC_EP_QUEUE) return -1;
    static const uint8_t expected_queue[24] = SDR_QUEUE_PREFIX;
    if (memcmp((void *)(SDR_ADDR_PRV_DWC_EP_QUEUE&~1u), expected_queue, 24)) return -1;
    wake = osiSemaphoreCreate(1, 0);
    if (!wake) return -1;
    for (uint32_t i=0; i<BUFFER_BYTES/4u; ++i)
        ((uint32_t *)buffer)[i] = ((i&4095u)<<4) | (((~i)&4095u)<<20);
    osiDCacheClean(buffer, sizeof(buffer));
    dbg_cache_barrier();
    raw.function.name = 0x51524453u; /* SDRQ */
    raw.function.ops = (struct usb_function_ops){fill,bind,unbind,destroy,function_setup,set_alt,disable};
    const uint8_t descriptor[9] = {9,4,0,0,1,0xff,0x53,0x44,0};
    memcpy(raw.interface_desc, descriptor, 9);
    raw.ep_desc = (struct usb_ep_descriptor){7,5,0x80,2,512,0};
    raw.interface_number = UINT32_MAX;
    if (!iot_os_create_task(worker, 0, 4096, 1, OPENAT_OS_CREATE_DEFAULT, "sdr_usb")) return -1;
    ((void (*)(void))SDR_ADDR_DRV_USB_DISABLE)();
    bool added = ((bool (*)(void *, struct usb_function *))SDR_ADDR_COPS_ADD_FUNCTION)(composite, &raw.function);
    if (added) {
        /* OS-descriptor negative results are cached by VID/PID/bcdDevice.
         * Give this descriptor generation a distinct device revision.
         */
        *(uint16_t *)((uint8_t *)composite+44) = 0x0101;
        int (**setup_slot)(void *, struct usb_setup *) = (void *)((uint8_t *)composite+12);
        original_setup = *setup_slot;
        *setup_slot = windows_setup;
        stats[2] = DBG_OK;
        stats[3] = raw.interface_number;
        stats[4] = raw.ep->address;
    }
    ((void (*)(uint32_t))SDR_ADDR_DRV_USB_ENABLE)(0);
    return added ? 0 : -1;
}

uint32_t sdr_raw_control(uint32_t op, const uint8_t *input, uint32_t size,
                         uint8_t *output, uint32_t *output_size)
{
    *output_size = 0;
    uint32_t key = osiEnterCritical();
    uint32_t result = DBG_OK;
    if (op == SDR_RAW_STATUS) {
        if (size) result = DBG_BAD_REQUEST;
        else {
            stats[3] = raw.interface_number;
            stats[4] = raw.ep ? raw.ep->address : 0;
            stats[5] = raw.enabled;
            for (unsigned i=0; i<SDR_RAW_STATS_WORDS; ++i) put32(output+i*4u, stats[i]);
            *output_size = SDR_RAW_STATS_WORDS*4u;
        }
    } else if (op == SDR_RAW_START) {
        if (size != 16 || dbg_u32(input) != SDR_RAW_ABI) result = DBG_BAD_REQUEST;
        else if (!raw.enabled || stats[2] != DBG_OK || raw.function.udc->speed != 3) result = DBG_NOT_READY;
        else if (start_requested || adapter.opened || stats[6] == 1 || stats[6] == 2
#ifdef DBG_ENABLE_BW0_USB
                 || capture_owned
#endif
                 ) result = DBG_BUSY;
        else {
            uint32_t ms = dbg_u32(input+4), bytes = dbg_u32(input+8), slots = dbg_u32(input+12);
            if (ms < 100 || ms > 60000 || bytes < 512 || bytes > 65024 || bytes%512 ||
                !slots || slots > IQ_USB_MAX_SLOTS || slots > BUFFER_BYTES/bytes || epoch == UINT32_MAX)
                result = DBG_RANGE;
            else {
                duration_ms = ms; block_bytes = bytes; slot_count = slots;
                ++epoch;
                stop_requested = 0;
                start_requested = 1;
                stats[6] = 1;
                put32(output, epoch);
                *output_size = 4;
            }
        }
    } else if (op == SDR_RAW_STOP) {
        if (size) result = DBG_BAD_REQUEST;
        else stop_requested = 1;
    } else result = DBG_UNSUPPORTED;
    osiExitCritical(key);
    if (result == DBG_OK && op != SDR_RAW_STATUS) notify(0);
    return result;
}
#ifdef DBG_ENABLE_BW0_USB
int sdr_raw_capture_acquire(struct sdr_udc **udc,struct sdr_usb_ep **ep,
    void (*stop)(void *),void *context)
{
    uint32_t key=osiEnterCritical();
    if(!udc || !ep || !stop || capture_owned || !raw.attached || !raw.enabled ||
        stats[2]!=DBG_OK || raw.function.udc->speed!=3 || start_requested ||
        adapter.opened || stats[6]==1 || stats[6]==2) {
        osiExitCritical(key); return 0;
    }
    capture_owned=1; capture_stop=stop; capture_context=context;
    *udc=raw.function.udc; *ep=raw.ep;
    osiExitCritical(key); return 1;
}
void sdr_raw_capture_release(void)
{
    uint32_t key=osiEnterCritical();
    if(capture_owned) {
        capture_owned=0; capture_stop=0; capture_context=0;
        if(!raw.attached && raw.ep) {
            raw.function.udc->ops.ep_free(raw.function.udc,raw.ep); raw.ep=0;
        }
    }
    osiExitCritical(key);
}
#endif
