#ifndef RF_CORE_RXON_PREPARE_B_MODE_H
#define RF_CORE_RXON_PREPARE_B_MODE_H
#include "rf_core_rxon_prepare.h"

/* Original RF0x50da..0x529c, only the mode-dependent analog middle.
 * saved_400/404 are the halfwords captured at original0x4ed6/4ee2, BEFORE
 * the prepare prefix, not fresh reads here. Local RF halfword bus.
 * Preserves native branches and repeated reads; does not admit unsupported
 * modes or bypass caller NV/route validation. No ready/lock guarantee.
 * On access failure returns -2 immediately without rollback. Not deployed.
 */
int rf_core_rxon_prepare_b_mode(const struct rf_core_rxon_prepare_bus *bus,
    uint32_t rxon_context, uint16_t saved_400, uint16_t saved_404);
#endif
