#ifndef SDR_SESSION_H
#define SDR_SESSION_H
#include "sdr_usb.h"
#include "sdr_control.h"
#ifdef __cplusplus
extern "C" {
#endif
struct sdr_session_result {
    struct sdr_usb_stats usb;
    uint32_t control_error, cleanup_error, epoch, device_drained;
    uint32_t status[48], recovery[24];
    uint64_t discarded_after_consumer_stop;
};
/* Optional separate output preserves the layout of sdr_session_result.
 * Device elapsed-time counters, excluding first500ms and last250ms; values
 * describe USB completions, not exact RF/sample-clock continuity. */
struct sdr_session_telemetry {
    uint32_t points,first_ms,last_ms,counter_invalid;
    uint64_t first_bytes,last_bytes;
    double minimum_window_bytes_per_second,maximum_window_bytes_per_second;
};
/* Blocking BW0/BW1 session on caller-owned, exclusively held handles.
 * duration_ms=0 requires advertised until-STOP/5s control-lease capability and
 * a consumer or stop callback. The control thread renews the lease every poll.
 * Otherwise duration remains100..60000ms. No fixed USB deadline is imposed.
 * INFO identity/capabilities and selected RF profile are checked before writes.
 * No other thread may use either handle until return. Control runs on a separate
 * thread; ready only signals an event, never performs serial I/O. Consumer stop
 * requests device STOP and discards subsequent data while draining (counted).
 * A successful return requires drained device evidence, not lossless sampling.
 * Result preserves USB, control and cleanup errors separately. Driver I/O can
 * block beyond software deadlines; this is not a bounded shutdown guarantee.
 * Handles remain caller-owned and can be reused after successful drain.
 */
uint32_t sdr_session_receive(sdr_usb *,sdr_control *,uint32_t band,
    uint32_t frequency_hz,uint32_t gain_index,uint32_t duration_ms,
    sdr_usb_consumer,void *,sdr_usb_stop_requested,void *,struct sdr_session_result *);
uint32_t sdr_session_receive_bw(sdr_usb *,sdr_control *,uint32_t band,
    uint32_t frequency_hz,uint32_t gain_index,uint32_t bandwidth_index,uint32_t duration_ms,
    sdr_usb_consumer,void *,sdr_usb_stop_requested,void *,struct sdr_session_result *);
uint32_t sdr_session_receive_observed(sdr_usb *,sdr_control *,uint32_t band,
    uint32_t frequency_hz,uint32_t gain_index,uint32_t bandwidth_index,uint32_t duration_ms,
    sdr_usb_consumer,void *,sdr_usb_stop_requested,void *,struct sdr_session_result *,struct sdr_session_telemetry *);
/* Offline parser also used by receive(); does not query a device. */
uint32_t sdr_session_validate_info(const char *,uint32_t bytes,uint32_t band);
uint32_t sdr_session_validate_info_bw(const char *,uint32_t bytes,uint32_t band,uint32_t bandwidth_index);
uint32_t sdr_session_validate_until_stop_info(const char *,uint32_t bytes,uint32_t band,uint32_t bandwidth_index);
/* band=0 in receive selects Auto. Pure INFO resolver filters advertised
 * profiles and current C envelopes; CONFIG still enforces runtime NV.
 * current=0 has no sticky preference. Does not access hardware or guess NV. */
uint32_t sdr_session_auto_route(const char *,uint32_t bytes,uint32_t frequency_hz,
    uint32_t current,uint32_t bandwidth_index,uint32_t continuous,uint32_t *selected_band);
#ifdef __cplusplus
}
#endif
#endif
