#ifndef UIS8910_RFAD_VARIABLE_H
#define UIS8910_RFAD_VARIABLE_H

#include "rf_bus.h"

enum rfad_variable_diagnostic {
    RFAD_DIAG_LTE_SPRD = 1,
    RFAD_DIAG_LTE_RDA = 2,
    RFAD_DIAG_LTE_UNCALIBRATED = 3,
    RFAD_DIAG_GSM_CALIBRATED = 4,
    RFAD_DIAG_GSM_UNCALIBRATED = 5
};

/* Version-bound rf_var_init state, CP BIN bd25923a.... globals addresses a
 * 0x2b4-byte block beginning at g_agc_index. Buffer cells contain the current
 * board-calibration addresses, not addresses copied from the CP load image.
 * framelen addresses two writable words. All objects and context must remain
 * mapped, stable and disjoint, under exclusive RF ownership. The diagnostic
 * callback may be null; when present it must not fail or modify RF memory.
 * It receives the original diagnostic arguments, with the format string
 * represented by the enum. The original formatting backend is not supplied. */
struct rfad_variable_context {
    uint32_t globals;
    uint32_t rfnv;
    uint32_t lte_buffer_cell;
    uint32_t gsm_buffer_cell;
    uint32_t cdac;
    uint32_t fdidle;
    uint32_t afc_flag;
    uint32_t fof_back;
    uint32_t fof_pair;
    uint32_t framelen;
    void *diagnostic_context;
    void (*diagnostic)(void *, uint32_t kind, const uint32_t *values, uint32_t count);
};

/* Reconstructs the complete RF data-state part of rf_var_init. Preserves
 * access widths/order, calibration selection and selective writes (holes are
 * retained). hwinit==0 retains the old AFC flag/FOF pair; other values seed
 * them from fof_back. This resets RX gain/BW to zero and installs default raw
 * RX/TX frequencies: it does not establish an active/tuned receiver. It does
 * not load calibration, request power, execute RFAD commands or touch DMA. */
void rfad_initialize_variables(const struct rf_bus *,
                               const struct rfad_variable_context *, uint32_t hwinit);

#endif
