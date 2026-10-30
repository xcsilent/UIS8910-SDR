#ifndef SDR_HOST_CONTROL_H
#define SDR_HOST_CONTROL_H
#include <stdint.h>
#include "sdr_bandwidth.h"
#include <wchar.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct sdr_control sdr_control;
#define SDR_CONTROL_MAX_PAYLOAD 4096u
#define SDR_CONTROL_DEVICE_ERROR 0x20000000u
/* One caller owns the COM context. IQ never passes through this interface.
 * The existing monitor CRC and same-sequence retries protect control only.
 * A timeout on START may mean it was accepted: inspect status and STOP/drain,
 * never infer that no RF job ran. close() does not issue STOP or reset.
 * Call INFO (operation1, JSON response) and validate advertised capabilities
 * before changing configuration. Open/typed methods do not infer RF support.
 * Poll control from a separate thread/context while USB reads are active;
 * synchronous COM I/O must not block the high-rate USB consumer callback.
 */
uint32_t sdr_control_open(sdr_control **result,const wchar_t *port,uint32_t timeout_ms);
void sdr_control_close(sdr_control *);
/* Only INFO and raw/BW0 service operations are allowed; no generic memory
 * access or CP invocation. Device errors are SDR_CONTROL_DEVICE_ERROR|status.
 * receive_bytes is in/out capacity/actual length; timeout has no valid body.
 */
uint32_t sdr_control_request(sdr_control *,uint32_t operation,const void *payload,
    uint32_t payload_bytes,void *receive,uint32_t *receive_bytes);
uint32_t sdr_control_configure(sdr_control *,uint32_t band,uint32_t frequency_hz,uint32_t gain_index);
/* BW0 keeps the legacy16-byte request. BW1 requires INFO config ABI2 and
 * explicit bandwidth capability checked by the caller/session API. */
uint32_t sdr_control_configure_bw(sdr_control *,uint32_t band,uint32_t frequency_hz,uint32_t gain_index,uint32_t bandwidth_index);
uint32_t sdr_control_start(sdr_control *,uint32_t duration_ms,uint32_t *epoch);
uint32_t sdr_control_stop(sdr_control *);
uint32_t sdr_control_keepalive(sdr_control *);
uint32_t sdr_control_status(sdr_control *,uint32_t words[48]);
uint32_t sdr_control_recovery(sdr_control *,uint32_t words[24]);
#ifdef __cplusplus
}
#endif
#endif
