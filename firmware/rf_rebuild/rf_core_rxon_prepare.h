#ifndef RF_CORE_RXON_PREPARE_H
#define RF_CORE_RXON_PREPARE_H
#include <stdint.h>

struct rf_core_rxon_prepare_bus {
    void *context;
    int (*read16)(void *, uint32_t, uint16_t *);
    int (*write16)(void *, uint32_t, uint16_t);
};
/* Local RF addresses, original ordered reads and halfword stores.
 * Entry is after coefficient commit; completion is gate 0xb3 before ready wait.
 * The caller retains ownership, timing, timeout recovery and later calibration. */
int rf_core_rxon_prepare_a(const struct rf_core_rxon_prepare_bus *bus,
                           uint32_t rxon_context);
#endif
