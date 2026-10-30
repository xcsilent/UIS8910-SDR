#ifndef SDR_BW0_USB_SERVICE_H
#define SDR_BW0_USB_SERVICE_H
#include <stdint.h>
#define SDR_BW0_STATUS 44u
#define SDR_BW0_START 45u
#define SDR_BW0_STOP 46u
#define SDR_BW0_CONFIG 47u
#define SDR_BW0_RECOVERY_STATUS 48u
#define SDR_BW0_KEEPALIVE 49u
#define SDR_BW0_SCHEDULER 50u
#define SDR_BW0_SEGMENTS 51u
#define SDR_BW0_SCRATCH_DROPS 52u
#define SDR_BW0_FEM_OVERRIDE 53u
#ifndef SDR_BW0_CONTINUOUS
#define SDR_BW0_CONTINUOUS 0
#endif
#define SDR_BW0_WORDS 48u
#define SDR_BW0_RECOVERY_WORDS 24u
#ifndef SDR_BW0_MAX_BW
#define SDR_BW0_MAX_BW 0u
#endif
struct sdr_bw0_backend {
    void *context;
    uint32_t (*prepare)(void *,const uint8_t *resident,uint32_t resident_bytes,
        const uint8_t *control,uint32_t control_bytes,uint32_t entry_offset,uint32_t generation,
        uint32_t channel,uint32_t gain,uint32_t raw_frequency,uint32_t bandwidth_index);
    int (*launch)(void *); /* 1 accepted, 0 definitely not submitted, -1 uncertain */
};
int sdr_bw0_install(volatile uint32_t *mailbox,struct sdr_bw0_backend);
uint32_t sdr_bw0_control(uint32_t,const uint8_t *,uint32_t,uint8_t *,uint32_t *);
/* The monitor must reject generic writes/CP commands while this is set.
 * DRAINED still owns the non-returning CP service; only explicit recovery
 * may reset that lifecycle. Status queries remain available.
 */
int sdr_bw0_busy(void);
#endif
