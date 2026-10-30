#ifndef RF_CORE_FREQUENCY_H
#define RF_CORE_FREQUENCY_H
#include <stdint.h>

struct rf_core_frequency_words {
    uint32_t working_raw;
    uint16_t factor_state, table_factor;
};
struct rf_core_frequency_coefficients {
    uint16_t q8, fraction_high, fraction_low, factor;
};

/* Pure replica of calculator arithmetic after resolving the two runtime tables.
 * RXON signed correction has already been applied to working_raw.
 * Selected factor zero is rejected before output publication. Other unusual
 * factors describe arithmetic only, not valid RF operating configurations. */
int rf_core_frequency_coefficients(const struct rf_core_frequency_words *in,
                                   struct rf_core_frequency_coefficients *out);
#endif
