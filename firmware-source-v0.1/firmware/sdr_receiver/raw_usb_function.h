#ifndef SDR_RAW_USB_FUNCTION_H
#define SDR_RAW_USB_FUNCTION_H

#include <stdint.h>

#define SDR_RAW_STATUS 40u
#define SDR_RAW_START 41u
#define SDR_RAW_STOP 42u
#define SDR_RAW_ABI 1u
#define SDR_RAW_STATS_WORDS 32u
#define SDR_RAW_GUID "{5D6BCE91-4F8A-4D42-9A0D-A9E6F8AC8910}"

/* Installs one exclusive vendor Bulk IN function. On boot this performs a
 * USB-only detach/reattach, before the monitor opens its control transport.
 * The first implementation benchmarks a fixed AP buffer, without RF/CP calls.
 */
int sdr_raw_install(void);
uint32_t sdr_raw_control(uint32_t op, const uint8_t *input, uint32_t size,
                         uint8_t *output, uint32_t *output_size);
#ifdef DBG_ENABLE_BW0_USB
struct sdr_udc;
struct sdr_usb_ep;
int sdr_raw_capture_acquire(struct sdr_udc **,struct sdr_usb_ep **,
    void (*stop)(void *),void *context);
void sdr_raw_capture_release(void);
#endif

#endif
