#ifndef UIS8910_RF_CORE_TUNE_PLAN_H
#define UIS8910_RF_CORE_TUNE_PLAN_H

#include <stdint.h>

struct rf_core_tune_input {
    uint16_t selector;
    uint16_t mode;
    uint16_t control_before;
    uint16_t q8;
    uint16_t fraction_low;
    uint16_t fraction_high;
    uint16_t mode_pair_first;
    uint16_t mode_pair_second;
    uint16_t polling_enabled;
};

struct rf_core_write16 {
    uint32_t local_address;
    uint16_t value;
    uint16_t reserved;
};

/* Pure plan builder: no hardware access and no CP/AP address alias implied.
 * Reconstructs the writes in RV 0x6420..0x66c0 with u16(0xb464)==0.
 * Coefficients and the mode-dependent constant pair must already be resolved
 * from the same exclusive working context. This is not a complete tune/init:
 * it excludes the input/correction calculation and the common tail helpers.
 * Nonzero polling_enabled is rejected, rather than disabling hardware polling.
 * Returns write count, -1 for invalid pointers/capacity, -2 for an unsupported
 * polling path. Output remains untouched on these errors. Input and output
 * must be disjoint and stable. */
int rf_core_make_retune_plan(const struct rf_core_tune_input *input,
                            struct rf_core_write16 *output, uint32_t capacity);

#endif
