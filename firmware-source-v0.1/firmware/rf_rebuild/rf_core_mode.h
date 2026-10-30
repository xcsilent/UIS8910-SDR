#ifndef UIS8910_RF_CORE_MODE_H
#define UIS8910_RF_CORE_MODE_H
#include <stdint.h>

struct rf_core_mode_bus {
    void *context;
    int (*read)(void *, uint32_t address, uint32_t width, uint32_t *value);
    int (*write)(void *, uint32_t address, uint32_t width, uint32_t value);
};

/* Offline reconstruction of original RF-local0x3a7c, NOT deployed firmware.
 * Caller owns the RF core and supplies correctly mapped, powered registers.
 * mode0..5 has the native BW argument mapping; no physical rate is promised.
 * Mode0 reads b550 separately for each NCO halfword; caller supplies index0..3.
 * Mode4/5 read selector b538; selectors5/15 use alternate control bits.
 * Returns0, -1 invalid contract/mode (no accesses) or mode0 index (after writes), -2 bus failure (immediate
 * stop, no rollback; caller must stop/recover before another transaction).
 * Preserve halfword access width and ordering. Do not use AP/CP addresses. */
int rf_core_apply_mode(const struct rf_core_mode_bus *, uint32_t mode);
#endif
