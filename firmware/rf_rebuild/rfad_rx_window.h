#ifndef UIS8910_RFAD_RX_WINDOW_H
#define UIS8910_RFAD_RX_WINDOW_H

#include "rf_bus.h"

/* Layout recovered from the shipped CP and CALIB_LTESFPARA_T DWARF.
 * The caller owns the calibration structures and keeps sf_ind stable in 0..9.
 * Frequency conversion is an explicit external dependency, not a hardware call
 * supplied by this library. No RF/DMA/IRQ start is performed here. */
struct rfad_calib_rx_context {
    uint32_t calibration;
    uint32_t subframes;
    uint32_t rf_info;
    void *frequency_context;
    void (*set_frequency)(void *context, uint32_t arfcn, uint32_t indicator);
};

void rfad_calib_rx_configure(const struct rf_bus *, const struct rfad_calib_rx_context *);
void rfad_rx_first_ofdm_offset(const struct rf_bus *, uint32_t offset);

#endif
