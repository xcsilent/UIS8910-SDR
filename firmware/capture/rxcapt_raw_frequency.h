#ifndef RXCAPT_RAW_FREQUENCY_H
#define RXCAPT_RAW_FREQUENCY_H
#include <stdint.h>

/* A raw override changes the RFAD target, retaining the anchor's RF path.
 * Sweep bounds are an explicit experiment envelope, never a silicon spec. */
static __attribute__((noinline,noclone)) uint32_t terminal_raw_frequency_valid(
    uint32_t raw, uint32_t anchor) {
    if (!raw) return 1u; /* zero selects the normal channel-derived target */
#if defined(RXCAPT_RAW_FREQUENCY_SWEEP) && RXCAPT_RAW_FREQUENCY_SWEEP
#if !defined(RXCAPT_RAW_SWEEP_MIN) || !defined(RXCAPT_RAW_SWEEP_MAX)
#error raw sweep requires explicit build bounds
#endif
    (void)anchor;
    return raw >= RXCAPT_RAW_SWEEP_MIN && raw <= RXCAPT_RAW_SWEEP_MAX;
#else
    return raw >= 23000000u && raw <= 23999000u &&
        (raw > anchor ? raw - anchor : anchor - raw) <= 1000u;
#endif
}
#endif
