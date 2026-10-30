#ifndef SDR_HOST_USB_H
#define SDR_HOST_USB_H
#include <stdint.h>
#include <wchar.h>

#ifdef __cplusplus
extern "C" {
#endif
typedef struct sdr_usb sdr_usb;
typedef int (*sdr_usb_consumer)(const void *, uint32_t, void *);
typedef void (*sdr_usb_ready)(void *);
typedef int (*sdr_usb_stop_requested)(void *);
struct sdr_usb_options { uint32_t request_bytes, requests, raw_io; };
struct sdr_usb_stats {
    uint64_t bytes, completions, short_reads, zero_reads;
    double elapsed_seconds, process_cpu_seconds;
    uint32_t win32_error, pipe_id, maximum_packet_bytes;
};
/* One context/stream per calling thread. Callback owns the buffer only until
 * it returns; return nonzero to stop. No sample parsing, copy, CRC or headers.
 */
uint32_t sdr_usb_find(wchar_t *path, uint32_t characters);
uint32_t sdr_usb_open(sdr_usb **result, const wchar_t *path, struct sdr_usb_options options);
uint32_t sdr_usb_receive(sdr_usb *, uint32_t duration_ms, sdr_usb_consumer, void *, struct sdr_usb_stats *);
/* Notify only after every initial read has been submitted. A controller may
 * then start the producer. This does not prove physical USB scheduling.
 */
uint32_t sdr_usb_receive_ready(sdr_usb *, uint32_t duration_ms, sdr_usb_consumer, void *,
    struct sdr_usb_stats *, sdr_usb_ready, void *ready_context);
/* Poll stop_requested between reads (at most 25 ms event wait). The controller
 * may pass duration_ms=0 to read until explicit stop; a stop callback is then
 * required. Nonzero duration remains a bounded 1..120000 ms fallback.
 * The controller must stop/drain the producer before signalling. Cancellation and a
 * blocking consumer can still delay return; this is not a bounded close API. */
uint32_t sdr_usb_receive_controlled(sdr_usb *, uint32_t duration_ms, sdr_usb_consumer, void *,
    struct sdr_usb_stats *, sdr_usb_ready, void *ready_context,
    sdr_usb_stop_requested, void *stop_context);
void sdr_usb_close(sdr_usb *);
#ifdef __cplusplus
}
#endif
#endif
