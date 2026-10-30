#ifndef RF_CORE_RXON_FINISH_H
#define RF_CORE_RXON_FINISH_H
#include <stdint.h>

enum rf_core_rxon_finish_stage {
    RF_FINISH_INITIAL, RF_FINISH_READY, RF_FINISH_TIMER,
    RF_FINISH_TIMER_CLEANUP, RF_FINISH_LATCH, RF_FINISH_CALIBRATION,
    RF_FINISH_MODE, RF_FINISH_FINAL, RF_FINISH_COMPLETE
};
struct rf_core_rxon_finish_bus {
    void *context;
    int (*read)(void *, uint32_t address, uint32_t width, uint32_t *value);
    int (*write)(void *, uint32_t address, uint32_t width, uint32_t value);
    /* Retained original 0x3a7c: includes DFE/FIR configuration, not demodulation. */
    int (*mode)(void *, uint32_t mode);
};
struct rf_core_rxon_finish_result {
    uint32_t stage, ready_reads, timer_reads, timer_timeout_cleanup_complete;
};
/* Shared original0x453c: table/context application only, no polling or lock
 * assertion. Valid table indices and exclusive context ownership are caller
 * preconditions. Returns0,-1 invalid bus,-2 bus error, no rollback. mode callback
 * is not required. RF-local addresses; offline, not linked into capture. */
int rf_core_rxon_apply_tables(const struct rf_core_rxon_finish_bus *bus,
                             uint32_t rxon_context);

/* Offline reconstruction, NOT installed RF firmware. Budgets are read counts,
 * not microseconds. Returns 0, -1 invalid contract, -2 bus error, -3 RF-ready
 * timeout, -4 timer timeout, -5 retained mode helper failure. On error the caller
 * must stop the transaction and reset; returning does not prove RF rollback.
 * Timer timeout attempts the original ack/disarm sequence, never further RF
 * configuration. Bus failure stops immediately, including during cleanup. */
int rf_core_rxon_finish_a(const struct rf_core_rxon_finish_bus *bus,
                         uint32_t rxon_context, uint32_t ready_budget,
                         uint32_t timer_budget,
                         struct rf_core_rxon_finish_result *result);
#endif
