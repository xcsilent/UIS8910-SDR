#ifndef RF_CORE_RXON_PREPARE_B_PREFIX_H
#define RF_CORE_RXON_PREPARE_B_PREFIX_H
#include "rf_core_rxon_prepare.h"

struct rf_core_rxon_b_saved { uint16_t reg400, reg404; };
/* Original0x4ecc..0x4f90, excluding ABI save trampoline at4ec8 and clock-mode
 * helper call at4f94. Snapshot400/404 is taken BEFORE any prepare writes.
 * Output is only published on success; hardware writes cannot be rolled back.
 * The next native step loads mode then calls0x4632 before coefficient commit.
 */
int rf_core_rxon_prepare_b_enter(const struct rf_core_rxon_prepare_bus *bus,
    uint32_t rxon_context, struct rf_core_rxon_b_saved *saved);
/* Original0x4f98..0x4fc4. Precomputed Q8/high/low in RF RAM b520/b522/b524;
 * does not calculate coefficients or prove the producer has completed.
 */
int rf_core_rxon_prepare_b_commit(const struct rf_core_rxon_prepare_bus *bus);
/* Original clock-mode helper0x4632. Ordered BBPLL2 REGA writes, no calibrated
 * physical time guarantee for the native NOPs on a different execution core.
 * Native mode>6 is a no-op; this is not permission to advertise extra modes.
 */
int rf_core_rxon_clock_mode(const struct rf_core_rxon_prepare_bus *bus, uint16_t mode);

/* Original RF0x4fc4..0x50da only, after B coefficient writes.
 * RF-local halfword bus; context+4 selects the original 10-byte analog row.
 * Caller supplies valid exclusive context/table memory and factor7..10 as
 * selected by native NV logic. This preserves native accesses, not a public
 * parameter validator. Success is NOT ready/lock or complete RX initialization.
 * Mode-specific remainder, calibration/latch and RF mode helper are excluded.
 * On bus failure stops immediately without rollback; caller retains ownership.
 * Not linked into the capture service or deployed.
 */
int rf_core_rxon_prepare_b_prefix(const struct rf_core_rxon_prepare_bus *bus,
                                   uint32_t rxon_context);
#endif
