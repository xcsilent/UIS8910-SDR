#include "rfad.h"

static uint32_t read32(const struct rf_bus *b, uint32_t a)
{
    return b->read(b->context, a, 4);
}

static uint16_t read16(const struct rf_bus *b, uint32_t a)
{
    return (uint16_t)b->read(b->context, a, 2);
}

static void write16(const struct rf_bus *b, uint32_t a, uint16_t v)
{
    b->write(b->context, a, v, 2);
}

static int32_t signed16(uint32_t v)
{
    v &= UINT32_C(0xffff);
    return v < UINT32_C(0x8000) ? (int32_t)v : (int32_t)v - 65536;
}

/* Match ASR #4 for negative values without an implementation-defined shift. */
static int32_t shift4(int32_t v)
{
    return v >= 0 ? v / 16 : -((15 - v) / 16);
}

static unsigned gain_table(uint16_t port)
{
    if (port == 1 || port == 7 || port == 5)
        return 1;
    return port == 0 ? 2 : 0;
}

uint32_t rfad_agc_word(const struct rf_bus *b, const struct rfad_rx_context *c,
                       uint32_t index, int16_t correction)
{
    uint16_t band = read16(b, c->info + 4);
    uint16_t port = read16(b, c->rfnv + 0xf0 + 4 * (uint32_t)band);
    uint16_t word = read16(b, c->new_agc[gain_table(port)] + 2 * index);
    int32_t fine = word & 0x7ff;
    if (word & 0x400)
        fine -= 2048;
    uint32_t result = (word & UINT32_C(0xf000)) |
                      ((uint32_t)(fine + correction) & UINT32_C(0x7ff));
    write16(b, c->lte_trace + 10, word);
    return result;
}

static uint32_t simple_gain(const struct rf_bus *b, const struct rfad_rx_context *c,
                            uint16_t index)
{
    uint32_t word = rfad_agc_word(b, c, index, 0);
    write16(b, c->lte_trace, index);
    write16(b, c->lte_trace + 14, (uint16_t)word);
    return word;
}

uint32_t rfad_agc_compensate(const struct rf_bus *b, const struct rfad_rx_context *c,
                             uint32_t index)
{
    if (index >= 125)
        index = 124;
    /* The original deliberately reloads this control word for each compare. */
    if (read32(b, c->ct_ctrl + 8) == UINT32_C(0xca11b002) ||
        read32(b, c->ct_ctrl + 8) == UINT32_C(0xca11b001) ||
        read32(b, c->ct_ctrl + 8) == UINT32_C(0xca11b003))
        return simple_gain(b, c, (uint16_t)index);

    uint32_t calib = read32(b, c->calib_tab_pointer);
    uint16_t bw = read16(b, c->rx_info + 28);
    uint16_t format = read16(b, calib + 20);
    uint16_t target = read16(b, c->rfnv + 0x184 + 2 * (uint32_t)bw);
    int32_t adjustment = signed16(format == 0xca01 ? target : (uint32_t)target - 32);
    uint16_t mode = read16(b, c->info + 40);
    if (mode == 1 || mode == 2) {
        uint16_t flags = read16(b, calib + 2);
        if (flags & (mode == 1 ? 2 : 16)) {
            int32_t desired = signed16((index - 25) * UINT32_C(16));
            unsigned i = 0;
            for (; i < 125; ++i) {
                if (signed16(read16(b, c->calib_gain + 2 * i)) > desired)
                    break;
            }
            unsigned chosen = i == 0 ? 0 : i - 1;
            int32_t actual = signed16(read16(b, c->calib_gain + 2 * chosen));
            int32_t correction = signed16((uint32_t)(desired - actual));
            if (correction > 160)
                correction = 160;
            else if (correction < -160)
                correction = -160;
            uint32_t word = rfad_agc_word(b, c, chosen, (int16_t)correction);
            write16(b, c->lte_trace, (uint16_t)desired);
            write16(b, c->lte_trace + 6, (uint16_t)actual);
            write16(b, c->lte_trace + 8, (uint16_t)chosen);
            write16(b, c->lte_trace + 12, (uint16_t)correction);
            write16(b, c->lte_trace + 14, (uint16_t)word);
            return word;
        }
    }

    uint32_t table = read32(b, c->rf_tab_pointer);
    if (read16(b, table + 16) != 0x5555 || read16(b, table + 32) != 0xabcd) {
        int32_t step = shift4(adjustment);
        uint16_t effective = signed16(index) <= step ? 0 : (uint16_t)((int32_t)index - step);
        return simple_gain(b, c, effective);
    }

    int32_t step = shift4(adjustment);
    uint16_t effective = signed16(index) <= step ? 0 : (uint16_t)((int32_t)index - step);
    uint16_t segment = read16(b, c->info + 8);
    uint16_t band = read16(b, c->info + 4);
    uint16_t offset = read16(b, table + 34 + 2 * (3 * (uint32_t)band + segment));
    int32_t adjusted = signed16((uint32_t)offset + 2 * (uint32_t)effective);
    if (adjusted >= 250)
        adjusted = 249;
    else if (adjusted < 0)
        adjusted = 0;
    uint16_t port = read16(b, c->rfnv + 0xf0 + 4 * (uint32_t)band);
    unsigned selection = gain_table(port);
    if (port == 0 && read16(b, c->info) == 34)
        selection = 1;
    uint32_t word = read16(b, c->agc[selection] + 2 * (uint32_t)adjusted);
    if (read16(b, table + 16) == 0x5555 && read16(b, table + 178) == 0xabcd) {
        uint16_t correction = read16(b, table + 180 +
                                      2 * (48 * (uint32_t)band + 16 * (uint32_t)segment + (word >> 12)));
        word = (word & UINT32_C(0xf000)) | ((word + correction) & UINT32_C(0x7ff));
    }
    return word;
}

void rfad_rxon_gain(const struct rf_bus *b, const struct rfad_rx_context *c,
                    uint32_t slots, uint16_t index)
{
    /* Wrapper reads mode even though the callee re-reads the global mode. */
    (void)read16(b, c->info + 40);
    uint32_t word = rfad_agc_compensate(b, c, index);
    uint32_t destination = read32(b, slots + 24);
    b->write(b->context, destination, word | UINT32_C(0x00540000), 4);
}

void rfad_rxon_parameters(const struct rf_bus *b, const struct rfad_rx_context *c,
                          uint32_t slots)
{
    uint16_t band = read16(b, c->info + 4);
    uint8_t soft_band = (uint8_t)b->read(b->context, c->info + 6, 1);
    uint32_t destination = read32(b, slots + 8);
    uint16_t bw = read16(b, c->rx_info + 28);
    uint16_t port = read16(b, c->rfnv + 0xf0 + 4 * (uint32_t)band);
    uint16_t packed = (uint16_t)(((uint32_t)soft_band << 8) | ((uint32_t)port << 4) | bw);
    b->write(b->context, destination, packed | UINT32_C(0x00500000), 4);
    uint16_t index = read16(b, c->rx_info + 2);
    rfad_rxon_gain(b, c, slots, index);
    rfad_rxon_frequency(b, slots, c->rx_info);
}
