#ifndef UIS8910_RF_FRONTEND_OVERRIDE_H
#define UIS8910_RF_FRONTEND_OVERRIDE_H
#include "rf_bus.h"

/* Experimental command-template substitution, never a direct RFFE transfer.
 * Caller owns CP/RF, has completed prepare, and must keep other RF users out.
 * bus callbacks provide device-view ordering and access widths. No live cache
 * or ownership protocol is implied by these helpers. Not enabled in v28.
 * An active state must survive failure until restoration or physical reset.
 */
struct rf_frontend_override {
    uint32_t address, original, replacement, active;
};
enum rf_frontend_override_result {
    RF_FEM_OVERRIDE_OK = 0,
    RF_FEM_OVERRIDE_INVALID = -1,
    RF_FEM_OVERRIDE_CONTEXT = -2,
    RF_FEM_OVERRIDE_READBACK = -3,
    RF_FEM_OVERRIDE_CONFLICT = -4
};
int rf_frontend_override_apply(const struct rf_bus *,
    struct rf_frontend_override *, uint32_t nv_row, uint32_t replacement_value,
    uint32_t receiver_idle);
/* Restore only after confirmed RF idle; a conflict is pinned, not overwritten.
 * Restore changes the template, not a previously transmitted switch state.
 */
int rf_frontend_override_restore(const struct rf_bus *,
    struct rf_frontend_override *, uint32_t receiver_idle);
#endif
