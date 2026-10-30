#ifndef UIS8910_RFAD_ANALOG_H
#define UIS8910_RFAD_ANALOG_H

#include "rf_bus.h"

enum rfad_analog_result {
    RFAD_ANALOG_OK = 0,
    RFAD_ANALOG_INVALID = -1,
    RFAD_ANALOG_WRITE_FAILED = -2
};

/* Reconstruct only the final ADI/SoC region of rf_lte_init_hw, CP BIN
 * bd25923a..., 0x801d8da2..0x801d8e12. nv is the original 22528-byte RF NV
 * object, not its copied RFNV parameters. The supplied ADI writer owns the
 * shared hardware lock and FIFO waiting; returning nonzero stops immediately
 * without issuing later writes. Bus, NV and callback context must remain
 * mapped, disjoint and stable under exclusive RF ownership. ADI offsets have
 * no inferred PLL/ADC meaning here. This does not initialize NV/descriptors,
 * power domains, RF clocks, calibration, RF events, DMA or a full cold boot.
 * An error leaves previously issued writes applied; no rollback is implied. */
int rfad_prepare_analog(const struct rf_bus *, uint32_t nv, void *context,
                        int (*adi_write)(void *, uint32_t offset, uint32_t value));

#endif
