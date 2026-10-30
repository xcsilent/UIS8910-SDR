#include "rfad.h"

static uint16_t read16(const struct rf_bus *b, uint32_t a)
{
    return (uint16_t)b->read(b->context, a, 2);
}

static uint32_t read32(const struct rf_bus *b, uint32_t a)
{
    return b->read(b->context, a, 4);
}

static void write16(const struct rf_bus *b, uint32_t a, uint16_t v)
{
    b->write(b->context, a, v, 2);
}

static void afc(const struct rf_bus *b, const struct rfad_afc_context *c,
                uint32_t slots, unsigned value_offset, unsigned control_offset)
{
    uint16_t card = read16(b, c->card_index);
    uint32_t frequency = read32(b, c->frequency_offset + 4 * (uint32_t)card);
    uint32_t temperature = read32(b, c->thermal_compensation + 4 * (uint32_t)card);
    uint32_t sum = frequency + temperature;
    /* Decode signed two's complement without overflowing signed C arithmetic. */
    int32_t value = sum & UINT32_C(0x80000000) ? -1 - (int32_t)~sum : (int32_t)sum;
    if (value > 32766)
        value = 32766;
    else if (value < -32766)
        value = -32766;
    uint32_t destination = read32(b, slots + value_offset);
    b->write(b->context, destination, UINT32_C(0x01000000) | (uint16_t)value, 4);
    destination = read32(b, slots + control_offset);
    b->write(b->context, destination, UINT32_C(0x00380020), 4);
}

void rfad_afc_commands(const struct rf_bus *b, const struct rfad_afc_context *c, uint32_t slots)
{
    afc(b, c, slots, 32, 36);
}

void rfad_afc_nodci_commands(const struct rf_bus *b, const struct rfad_afc_context *c, uint32_t slots)
{
    afc(b, c, slots, 124, 128);
}

void rfad_load_nv_parameters(const struct rf_bus *b, uint32_t nv, uint32_t rfnv)
{
    static const struct { uint16_t destination; uint16_t halfwords; } spans[] = {
        {0, 0x10}, {0x20, 0x146}, {0x2ac, 0x8be}, {0x1428, 0x2c4},
        {0x19cc, 0x6c0}, {0x274c, 0x24e}, {0x3e20, 0x7e}, {0x2be8, 0x512},
        {0x373c, 0x242}, {0x3f1c, 0x20}, {0x3bc0, 0x12c}, {0x19b0, 0xe},
        {0x3e18, 4}, {0x360c, 0x2c}, {0x3664, 0x1a}, {0x3698, 0x1a}
    };
    for (unsigned i = 0; i < sizeof(spans) / sizeof(spans[0]); ++i) {
        uint32_t destination = spans[i].destination;
        uint32_t source = destination + (destination == 0 ? 0 : 0x1800);
        for (unsigned j = 0; j < spans[i].halfwords; ++j) {
            uint16_t value = read16(b, nv + source + 2 * j);
            write16(b, rfnv + destination + 2 * j, value);
        }
    }
    if (read32(b, rfnv + 0x3d5c) != UINT32_C(0x5555aaaa)) {
        for (unsigned i = 0; i < 20; ++i) {
            b->write(b->context, rfnv + 0x3d60 + i, 0, 1);
            b->write(b->context, rfnv + 0x3d74 + i, 0, 1);
            b->write(b->context, rfnv + 0x3d88 + i, 0, 1);
        }
    }
}

void rfad_apply_nv_channel_tables(const struct rf_bus *b, uint32_t rfnv, uint32_t tables)
{
    for (unsigned i = 0; i < 24; ++i) {
        uint16_t band = read16(b, rfnv + 0x20 + 2 * i);
        if (band == 41) {
            uint16_t flag = read16(b, rfnv + 0x52 + 4 * i);
            uint16_t minimum, maximum, middle, frequency, segment;
            if (flag == 100) {
                minimum = 40240; maximum = 41240; middle = 40740; frequency = 25550; segment = 333;
            } else if (flag == 120) {
                minimum = 40040; maximum = 41240; middle = 40640; frequency = 25350; segment = 400;
            } else if (flag == 140) {
                minimum = 40040; maximum = 41440; middle = 40740; frequency = 25350; segment = 466;
            } else {
                return;
            }
            write16(b, tables + 46, minimum);
            write16(b, tables + 0x36 + 46, maximum);
            write16(b, tables + 0x6c + 46, middle);
            write16(b, tables + 0xa2 + 46, frequency);
            write16(b, tables + 0xd8 + 46, frequency);
            write16(b, tables + 0x10e + 46, segment);
            return;
        }
        if (band == 28 && read16(b, rfnv + 0x52 + 4 * i) == 0) {
            write16(b, tables - 0x36 + 22, 28);
            write16(b, tables + 22, 9210);
            write16(b, tables + 0x36 + 22, 9659);
            write16(b, tables + 0x6c + 22, 9435);
            write16(b, tables + 0xa2 + 22, 7580);
            write16(b, tables + 0xd8 + 22, 7030);
            write16(b, tables + 0x10e + 22, 150);
        }
    }
}

void rfad_set_system_clock(const struct rf_bus *b, uint32_t clock)
{
    const uint32_t address = UINT32_C(0x50035000);
    if (clock == UINT32_C(122880000)) {
        b->write(b->context, address, 0x824, 4);
        b->write(b->context, address, 0xc24, 4);
        b->write(b->context, address, 0x24, 4);
        return;
    }
    uint32_t value = 0x800;
    if (clock == UINT32_C(40960000)) value = 0x2c;
    else if (clock == UINT32_C(81920000)) value = 0x26;
    else if (clock == UINT32_C(140430000)) value = 0x47;
    else if (clock == UINT32_C(163840000)) value = 0x23;
    b->write(b->context, address, value, 4);
    value = read32(b, address);
    b->write(b->context, address, value | UINT32_C(0x400), 4);
}
