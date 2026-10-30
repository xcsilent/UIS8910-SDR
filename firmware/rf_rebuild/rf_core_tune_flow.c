#include "rf_core_tune_flow.h"

static uint32_t divide_u32(uint32_t numerator, uint32_t denominator,
                           uint32_t *remainder_out)
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
    if (remainder_out)
        *remainder_out = remainder;
    return quotient;
}

int rf_core_calculate_tune_parameters(const struct rf_core_frequency_input *in,
                                     struct rf_core_frequency_output *out)
{
    static const int16_t corrections[2][4] = {
        {7000, -7000, 0, 0}, {-2000, -1000, 0, 1000}
    };
    static const uint16_t mode_pairs[2][4][2] = {
        {{0x5555, 0x0017}, {0xaaab, 0x00e8}, {0, 0}, {0x5556, 0x00e5}},
        {{0x5556, 0x00e5}, {0xaaab, 0x00f2}, {0, 0}, {0x5555, 0x000d}}
    };
    struct rf_core_frequency_output result;
    uint32_t working, effective, factor, denominator, remainder;
    uint32_t q8_whole, q8_remainder, whole, fractional = 0;
    int16_t correction = 0;
    uint16_t pair_first = 0, pair_second = 0;
    unsigned i;

    if (!in || !out || in->mode > 6u || in->correction_index > 3u)
        return -1;
    if (in->mode == 0u || in->mode == 6u) {
        unsigned row = in->mode == 0u ? 0u : 1u;
        correction = corrections[row][in->correction_index];
        pair_first = mode_pairs[row][in->correction_index][0];
        pair_second = mode_pairs[row][in->correction_index][1];
    }
    factor = in->factor_state == 1u ? in->table_factor : 7u;
    if (!factor || factor > 0xffffffffu / 260000u)
        return -1;

    working = in->requested_raw + (uint32_t)(int32_t)correction;
    effective = working < 10000000u ? working * 2u : working;
    q8_whole = divide_u32(effective, 260000u, &q8_remainder);
    denominator = 260000u * factor;
    whole = divide_u32(effective, denominator, &remainder);
    for (i = 0; i < 28u; ++i) {
        uint32_t carry = remainder >> 31;
        uint32_t doubled = (remainder << 1) | 0u;
        fractional <<= 1;
        if (carry || doubled >= denominator) {
            remainder = doubled - denominator;
            fractional |= 1u;
        } else {
            remainder = doubled;
        }
    }

    result.working_raw = working;
    result.effective_raw = effective;
    result.fraction = (whole << 28) | fractional;
    result.correction = correction;
    result.denominator_factor = (uint16_t)factor;
    result.q8 = (uint16_t)((q8_whole << 8) +
                           ((q8_remainder << 8) / 260000u));
    result.mode_pair_first = pair_first;
    result.mode_pair_second = pair_second;
    result.reserved = 0;
    *out = result;
    return 0;
}

static int context_read16(const struct rf_core_context_bus *bus, uint32_t address,
                          uint16_t *value)
{
    if (bus->read16(bus->context, address, value))
        return -2;
    return 0;
}

static uint16_t retune_correction_index(uint32_t argument)
{
    /* p.extractu a4,a0,1,13 at RV 0x6390: one unsigned bit at position 13. */
    return (uint16_t)((argument >> 13) & 1u);
}

int rf_core_resolve_tune_request(const struct rf_core_context_bus *bus,
                                uint32_t requested_raw,
                                uint32_t retune_argument,
                                struct rf_core_tune_request *out)
{
    struct rf_core_tune_request result;
    uint16_t selector, slot, factor_state, lookup;
    uint32_t index;
    int status;

    if (!bus || !bus->read16 || !out || !(retune_argument & 1u))
        return -1;
    /* Shared RISC-V working context. Selector/slot bounds come from the
     * reconstructed 15-entry table row and 0..20 selector split. */
    if ((status = context_read16(bus, 0x5000b530u, &result.frequency.mode)) ||
        (status = context_read16(bus, 0x5000b538u, &selector)) ||
        (status = context_read16(bus, 0x5000b544u, &slot)) ||
        (status = context_read16(bus, 0x5000b546u, &result.context_16)) ||
        (status = context_read16(bus, 0x5000a710u, &factor_state)) ||
        (status = context_read16(bus, 0x5000b464u, &result.polling_enabled)))
        return status;
    if (result.frequency.mode > 6u || selector > 20u || slot > 14u)
        return -1;

    result.frequency.requested_raw = requested_raw;
    result.frequency.correction_index = retune_correction_index(retune_argument);
    result.frequency.factor_state = factor_state;
    result.frequency.table_factor = 0;
    result.selector = selector;
    result.table_slot = slot;

    /* This handler selects the same A/B control halfword as the reconstructed
     * RISC-V path: selectors 0..12 and 17 use B, all other valid selectors A. */
    if (selector <= 12u || selector == 17u)
        status = context_read16(bus, 0x50030364u, &result.control_before);
    else
        status = context_read16(bus, 0x50030374u, &result.control_before);
    if (status)
        return status;
    if ((status = context_read16(bus, 0x50032004u, &result.control_32004_before)))
        return status;

    index = 15u * selector + slot;
    if ((status = context_read16(bus, 0x50008764u + 2u * index, &result.word_8764)) ||
        (status = context_read16(bus, 0x50009438u + 2u * index, &result.word_9438)) ||
        (status = context_read16(bus, 0x5000af78u + 4u * index,
                                 &result.pair_af78_first)) ||
        (status = context_read16(bus, 0x5000af7au + 4u * index,
                                 &result.pair_af78_second)))
        return status;

    /* The live factor path is conditional. The table selector comes from the
     * first-level 0x940c table; its result indexes the runtime 0xa714 table. */
    if (factor_state == 1u) {
        if ((status = context_read16(bus, 0x5000940cu + 2u * selector, &lookup)))
            return status;
        if (lookup >= 1024u)
            return -1;
        if ((status = context_read16(bus, 0x5000a714u + 2u * lookup,
                                     &result.frequency.table_factor)))
            return status;
        if (!result.frequency.table_factor)
            return -1;
    }
    /* The frequency calculator itself rejects values that cannot form its
     * 32-bit denominator, before the output request is published. */
    {
        struct rf_core_frequency_output calculated;
        if (rf_core_calculate_tune_parameters(&result.frequency, &calculated))
            return -1;
    }
    *out = result;
    return 0;
}

static void add(struct rf_core_flow_step *out, uint32_t *count, uint32_t op,
                uint32_t address, uint32_t value, uint32_t mask)
{
    struct rf_core_flow_step *step = out + (*count)++;
    step->operation = op;
    step->local_address = address;
    step->value = value;
    step->mask = mask;
}

static uint32_t frequency_word(uint32_t frequency)
{
    static const uint32_t starts[6] = {
        7820000, 17620000, 19600000, 21580000, 23560000, 25540000
    };
    uint32_t i;
    for (i = 0; i < 6; ++i)
        if (frequency - starts[i] <= (i ? 400000u : 300000u))
            return 0x1db13b13;
    return 0x1e762762;
}

int rf_core_rxon_post_configure(const struct rf_core_flow_bus *bus,
                                uint32_t requested_raw, uint16_t mode)
{
    uint32_t control, selector, center, width, i;
    int profile = 0;
    if (!bus || !bus->read || !bus->write || mode > 6u) return -1;
#define READ(a,w,v) do { if (bus->read(bus->context,(a),(w),&(v))) return -2; } while (0)
#define WRITE(a,w,v) do { if (bus->write(bus->context,(a),(w),(v))) return -2; } while (0)
    READ(0x32004u,2,control); control &= 0xffffu;
    WRITE(0x50109050u,4,frequency_word(requested_raw));
    READ(0xb538u,2,selector); selector &= 0xffffu;
    if (selector == 5u) {
        profile = 1;
    } else {
        /* Native loads the first center before the indexed width word and
         * does not read later centers once an inclusive match is found. */
        READ(0x8530u,4,center);
        READ(0x91a0u + 4u*mode,4,width);
        for (i = 0; i < 4u; ++i) {
            if (i) READ(0x8530u + 4u*i,4,center);
            if (requested_raw >= center-width && requested_raw <= center+width) {
                profile = selector != 1u || mode <= 3u ||
                          requested_raw-19620001u <= 79999u;
                break;
            }
        }
    }
    WRITE(0x3033cu,2,profile ? 0x282cu : 0x25cfu);
    WRITE(0x30340u,2,profile ? 0x1c5bu : 0x29bfu);
    WRITE(0x3030cu,2,profile ? 0x2a80u : 0x2800u);
    WRITE(0x30310u,2,0);
    WRITE(0x32004u,2,profile ? control|0x100u : control&~0x100u);
#undef READ
#undef WRITE
    return 0;
}

static int tail_profile(uint32_t frequency, uint16_t selector, uint16_t mode)
{
    static const uint32_t centers[4] = {19660800, 18432000, 25804800, 23961600};
    static const uint32_t widths[7] = {7000, 15000, 25000, 50000, 75000, 100000, 2000};
    uint32_t i, width = widths[mode];
    if (selector == 5)
        return 1;
    for (i = 0; i < 4; ++i) {
        if (frequency >= centers[i] - width && frequency <= centers[i] + width) {
            if (selector == 1 && mode > 3)
                return frequency - 19620001u <= 79999u;
            return 1;
        }
    }
    return 0;
}

int rf_core_build_tune_flow(const struct rf_core_flow_input *in,
                           struct rf_core_flow_step *out, uint32_t capacity)
{
    struct rf_core_tune_input prefix;
    struct rf_core_write16 base[11];
    uint32_t i, count = 0, required;
    int n, bank_a, polling, profile;
    uint16_t control;
    if (!in || !out || in->prefix.selector > 20 || in->prefix.mode > 6 || in->table_slot > 14)
        return -1;
    prefix = in->prefix;
    prefix.polling_enabled = 0; /* Reuse the pure base plan; retain the original gate below. */
    n = rf_core_make_retune_plan(&prefix, base, 11);
    if (n < 0)
        return -1;
    bank_a = prefix.selector > 12 && prefix.selector != 17;
    polling = bank_a && in->prefix.polling_enabled != 0;
    required = (uint32_t)n + 15 + (polling ? 7 : 0);
    if (capacity < required)
        return -1;

    for (i = 0; i < (uint32_t)n; ++i) {
        if (polling && i == 2) {
            add(out, &count, RF_CORE_WRITE16, 0x31040, 0, 0);
            add(out, &count, RF_CORE_WRITE16, 0x30454, 0x300a, 0);
        }
        add(out, &count, RF_CORE_WRITE16, base[i].local_address, base[i].value, 0);
        if (polling && i == (uint32_t)n - 2) {
            add(out, &count, RF_CORE_POLL16, 0x3037c, 0x800, 0x800);
            add(out, &count, RF_CORE_TIMER_WAIT, 0x38000, 122, 0);
            /* RV 0x6592 reads the live register after the wait; 0x659a ORs
             * 0x130. Do not assume the prior 0x300a write reads back intact. */
            add(out, &count, RF_CORE_OR16, 0x30454, 0x130, 0);
            add(out, &count, RF_CORE_WRITE16, 0x31040, 2, 0);
            add(out, &count, RF_CORE_WRITE16, 0x31040, 3, 0);
        }
    }
    add(out, &count, RF_CORE_WRITE32, 0x50109050, frequency_word(in->requested_raw), 0);
    profile = tail_profile(in->requested_raw, prefix.selector, prefix.mode);
    add(out, &count, RF_CORE_WRITE16, 0x3033c, profile ? 0x282c : 0x25cf, 0);
    add(out, &count, RF_CORE_WRITE16, 0x30340, profile ? 0x1c5b : 0x29bf, 0);
    add(out, &count, RF_CORE_WRITE16, 0x3030c, profile ? 0x2a80 : 0x2800, 0);
    add(out, &count, RF_CORE_WRITE16, 0x30310, 0, 0);
    control = profile ? in->control_32004_before | 0x100 :
                        in->control_32004_before & (uint16_t)~0x100;
    add(out, &count, RF_CORE_WRITE16, 0x32004, control, 0);
    add(out, &count, RF_CORE_WRITE16, 0x30448, in->word_8764, 0);
    add(out, &count, RF_CORE_WRITE16, 0x3044c, prefix.mode == 6 ? 0x9534 : 0xad34, 0);
    add(out, &count, RF_CORE_WRITE16, 0x32020, in->context_16 | 0x1000, 0);
    add(out, &count, RF_CORE_WRITE16, 0x32128, 0x1000, 0);
    add(out, &count, RF_CORE_WRITE16, 0x32008, 1, 0);
    add(out, &count, RF_CORE_WRITE16, 0x3201c, 0xa02, 0);
    add(out, &count, RF_CORE_WRITE16, 0x30474, in->word_9438, 0);
    add(out, &count, RF_CORE_WRITE16, 0x3200c, in->pair_af78_first, 0);
    add(out, &count, RF_CORE_WRITE16, 0x32010, in->pair_af78_second, 0);
    return (int)count;
}

int rf_core_build_tune_flow_request(const struct rf_core_tune_request *request,
                                   struct rf_core_flow_step *out, uint32_t capacity)
{
    struct rf_core_frequency_output frequency;
    struct rf_core_flow_input flow;
    int status;
    if (!request || !out)
        return -1;
    status = rf_core_calculate_tune_parameters(&request->frequency, &frequency);
    if (status)
        return status;
    flow.requested_raw = request->frequency.requested_raw;
    flow.prefix.selector = request->selector;
    flow.prefix.mode = request->frequency.mode;
    flow.prefix.control_before = request->control_before;
    flow.prefix.q8 = frequency.q8;
    flow.prefix.fraction_low = (uint16_t)frequency.fraction;
    flow.prefix.fraction_high = (uint16_t)(frequency.fraction >> 16);
    flow.prefix.mode_pair_first = frequency.mode_pair_first;
    flow.prefix.mode_pair_second = frequency.mode_pair_second;
    flow.prefix.polling_enabled = request->polling_enabled;
    flow.table_slot = request->table_slot;
    flow.context_16 = request->context_16;
    flow.word_8764 = request->word_8764;
    flow.word_9438 = request->word_9438;
    flow.pair_af78_first = request->pair_af78_first;
    flow.pair_af78_second = request->pair_af78_second;
    flow.control_32004_before = request->control_32004_before;
    return rf_core_build_tune_flow(&flow, out, capacity);
}

static int wait_for(const struct rf_core_flow_bus *bus, uint32_t address,
                    uint32_t bytes, uint32_t mask, uint32_t target, uint32_t budget)
{
    uint32_t value;
    while (budget--) {
        if (bus->read(bus->context, address, bytes, &value))
            return -2;
        if ((value & mask) == target)
            return 0;
    }
    return -3;
}

int rf_core_execute_tune_flow(const struct rf_core_flow_step *steps, uint32_t count,
                             const struct rf_core_flow_bus *bus, uint32_t budget)
{
    uint32_t i, value;
    int status;
    if (!steps || !bus || !bus->read || !bus->write || !budget)
        return -1;
    for (i = 0; i < count; ++i) {
        const struct rf_core_flow_step *s = steps + i;
        if (s->operation == RF_CORE_WRITE16 || s->operation == RF_CORE_WRITE32) {
            if (bus->write(bus->context, s->local_address,
                           s->operation == RF_CORE_WRITE16 ? 2 : 4, s->value))
                return -2;
        } else if (s->operation == RF_CORE_OR16) {
            if (bus->read(bus->context, s->local_address, 2, &value) ||
                bus->write(bus->context, s->local_address, 2,
                           (value | s->value) & 0xffffu))
                return -2;
        } else if (s->operation == RF_CORE_POLL16) {
            status = wait_for(bus, s->local_address, 2, s->mask, s->value, budget);
            if (status)
                return status;
        } else if (s->operation == RF_CORE_TIMER_WAIT) {
            uint32_t a = s->local_address;
            if (bus->read(bus->context, a, 4, &value) ||
                bus->write(bus->context, a, 4, value & ~11u) ||
                bus->write(bus->context, a + 4, 4, 0) ||
                bus->write(bus->context, a + 8, 4, s->value) ||
                bus->write(bus->context, a + 12, 4, 1) ||
                bus->write(bus->context, a, 4, 11))
                return -2;
            status = wait_for(bus, a + 12, 4, 1, 1, budget);
            if (status)
                return status;
            if (bus->write(bus->context, a + 12, 4, 1) ||
                bus->read(bus->context, a, 4, &value) ||
                bus->write(bus->context, a, 4, value & ~11u))
                return -2;
        } else {
            return -1;
        }
    }
    return 0;
}
