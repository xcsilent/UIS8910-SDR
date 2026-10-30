#ifndef UIS8910_RFAD_BOOT_MEMORY_H
#define UIS8910_RFAD_BOOT_MEMORY_H

#include "rf_bus.h"

enum rfad_boot_memory_result {
    RFAD_BOOT_MEMORY_OK = 0,
    RFAD_BOOT_MEMORY_INVALID = -1,
    RFAD_BOOT_MEMORY_MISSING = -2,
    RFAD_BOOT_MEMORY_NAME = -3
};

/* CP BIN bd25923a... boot table: 64 entries at 0x80000000, stride 32,
 * name at +0, address/length at +20/+24. Returns the first matching pair.
 * Null query/output returns -1 without writes; otherwise clears the output
 * pair before searching, as hal_getMemInfo does. Addresses are bus addresses.
 * Unlike the original unbounded strcmp, query and each visited name must
 * terminate within 20 bytes (19 characters); a malformed name returns -3.
 * Output remains zero on -2/-3. Bus/table/query/output must be mapped, stable
 * and disjoint; output must be aligned and writable for eight bytes. The bus
 * must be valid. This is not a general pointer validator or a payload loader.
 * A successful lookup copies raw fields, including zero/invalid fields.
 * Before consuming calibration, the caller must independently validate its
 * board provenance, mapped address, length and required layout. No RF or DMA
 * is started here, and no default calibration is installed. */
int32_t rfad_boot_get_memory(const struct rf_bus *, uint32_t query, uint32_t output);

#endif
