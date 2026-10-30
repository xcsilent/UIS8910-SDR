#include "rf_core_frequency.h"

static uint32_t divide(uint32_t numerator, uint32_t denominator, uint32_t *rest)
{
    uint32_t quotient = 0, remainder = 0;
    int bit;
    for (bit = 31; bit >= 0; --bit) {
        uint32_t carry = remainder >> 31;
        remainder = (remainder << 1) | ((numerator >> bit) & 1u);
        if (carry || remainder >= denominator) {
            remainder -= denominator;
            quotient |= 1u << bit;
        }
    }
    *rest = remainder;
    return quotient;
}

int rf_core_frequency_coefficients(const struct rf_core_frequency_words *in,
                                   struct rf_core_frequency_coefficients *out)
{
    struct rf_core_frequency_coefficients result;
    uint32_t effective, factor, denominator, whole, remainder, fraction = 0;
    unsigned bit;
    if (!in || !out)
        return -1;
    factor = in->factor_state == 1u ? in->table_factor : 7u;
    if (!factor)
        return -1;
    effective = in->working_raw < 10000000u ? in->working_raw * 2u : in->working_raw;
    whole = divide(effective, 260000u, &remainder);
    result.q8 = (uint16_t)((whole << 8) + divide(remainder << 8, 260000u, &remainder));
    denominator = factor * 260000u; /* Original MUL low 32 bits, followed by SRAI. */
    if (!(denominator & 0x80000000u)) {
        whole = divide(effective, denominator, &remainder);
        for (bit = 0; bit < 28u; ++bit) {
            uint32_t carry = remainder >> 31;
            remainder <<= 1;
            fraction <<= 1;
            if (carry || remainder >= denominator) {
                remainder -= denominator;
                fraction |= 1u;
            }
        }
        fraction |= whole << 28;
    }
    /* Sign extension makes a negative 32-bit product a huge unsigned 64-bit
     * divisor, larger than every numerator produced by this 32-bit input. */
    result.fraction_high = (uint16_t)(fraction >> 16);
    result.fraction_low = (uint16_t)fraction;
    result.factor = (uint16_t)factor;
    *out = result;
    return 0;
}
