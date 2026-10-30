#ifndef SDR_USB_SEGMENT_PROFILE_H
#define SDR_USB_SEGMENT_PROFILE_H
#include <stdint.h>
enum {USB_PROFILE_PREPARE,USB_PROFILE_ENQUEUE,USB_PROFILE_COMPLETE,USB_PROFILE_STAGES};
#define USB_PROFILE_WORDS 40u
/* Single receiver owner. Caller serializes configuration/reset/snapshot with
 * worker and completion callbacks. No payload inspection or logging. */
uint64_t sdr_usb_profile_clock(void);
int usb_segment_profile_enabled(void);
int usb_segment_profile_configure(uint32_t enabled);
void usb_segment_profile_reset(void);
void usb_segment_profile_record(unsigned stage,uint64_t start,uint64_t end);
void usb_segment_profile_exchange(uint32_t released,uint32_t claimed);
void usb_segment_profile_words(uint32_t out[USB_PROFILE_WORDS]);
/* Bounded AP-observed refill timelines, separate wire ABI. Offsets share
 * the empty-completion origin; they are not additive stage durations.
 * Caller holds the same critical section as UDC callbacks. */
enum {USB_REFILL_WORKER,USB_REFILL_RELEASE,USB_REFILL_ACK,USB_REFILL_PUBLISHED,USB_REFILL_EVENTS};
#define USB_REFILL_SAMPLES 24u
#define USB_REFILL_WORDS (10u+8u*USB_REFILL_SAMPLES)
void usb_refill_begin(uint64_t now);
int usb_refill_active(void);
void usb_refill_event(unsigned event,uint64_t now,uint32_t context);
void usb_refill_end(int successful,uint64_t now);
void usb_refill_words(uint32_t out[USB_REFILL_WORDS]);
#endif
