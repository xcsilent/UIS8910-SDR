#ifndef UIS8910_RF_BUS_H
#define UIS8910_RF_BUS_H

#include <stdint.h>

/* Explicit 32-bit CP addresses, independent of the host pointer size.
 * Callbacks perform exactly one access of width 1, 2 or 4, in program order.
 * Callers supply mapped, aligned addresses and exclusive RF ownership.
 * No physical bus, power, cache or timing guarantees are implied here. */
struct rf_bus {
    void *context;
    uint32_t (*read)(void *context, uint32_t address, unsigned width);
    void (*write)(void *context, uint32_t address, uint32_t value, unsigned width);
};

#endif
