#ifndef UIS8910_RFAD_BOOT_INPUTS_H
#define UIS8910_RFAD_BOOT_INPUTS_H

#include "rf_bus.h"

/* Replica of hal_writeRfBand's NV accesses. Returns 1 without NV writes if
 * the high byte is not 0x5e, otherwise returns 0. map is the version-bound
 * 32-byte ROM band map; only bits/entries 0..23 are interpreted. Special
 * map value 28 enables all NV list entries 650/651. Other bands enable only
 * the first match. The enabled halfwords are NV+0x1850+4*i; neighboring flag
 * halfwords are preserved. An accepted zero-payload mask disables all rows.
 * This is a board policy edit, not an RF frequency/PLL operation. */
int rfad_apply_boot_band_mask(const struct rf_bus *, uint32_t nv,
                              uint32_t mask, const uint8_t map[32]);

enum rfad_boot_inputs_result {
    RFAD_BOOT_INPUTS_OK = 0,
    RFAD_BOOT_INPUTS_MISSING = -1,
    RFAD_BOOT_INPUTS_LAYOUT = -2,
    RFAD_BOOT_INPUTS_RANGE = -3
};

/* Resolve rf_nv.bin, lte_rf_calib.bin and gsm_rf_calib.bin from the 64-entry
 * AP boot table. Version-specific reserved lengths are 22528/32768/8192 B.
 * After all three descriptors pass bounds/alignment/non-overlap checks,
 * copy board RF NV into 0x8048355c, apply the supplied band policy, and
 * publish both calibration address/length pairs at 0x80476710/0x80476730.
 * Descriptor-query scratch writes stay on the caller's stack on rejection;
 * no destination NV or calibration-cell writes precede validation.
 * Does not register NV callbacks, mark modem NV initialized, create tasks,
 * initialize hardware, load files or supply default calibration. Existing
 * AP boot must already have loaded valid board payloads; descriptor metadata
 * and this copy do not certify payload checksums or factory-file read success.
 * Caller owns these globals exclusively, supplies a valid bus/map, and
 * handles cache publication before another core reads the destination.
 */
/* Validate all three AP boot descriptors without modifying CP input memory. */
int rfad_validate_boot_inputs(const struct rf_bus *);

int rfad_restore_boot_inputs(const struct rf_bus *, uint32_t band_mask,
                              const uint8_t map[32]);

#endif
