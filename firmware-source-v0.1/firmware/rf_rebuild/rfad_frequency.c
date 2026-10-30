#include "rfad.h"

static uint16_t read16(const struct rf_bus *bus, uint32_t address)
{
    return (uint16_t)bus->read(bus->context, address, 2);
}

/* Keep the vendor's short-circuit reads, first-match selection, and fallback
 * behavior in this low-level replica. Tables may be modified by NV init. */
static unsigned find_channel(const struct rf_bus *bus, uint32_t tables,
                             uint16_t channel)
{
    for (unsigned i = 0; i < 27; ++i) {
        if (read16(bus, tables + 2 * i) <= channel &&
            read16(bus, tables + 0x36 + 2 * i) >= channel)
            return i;
    }
    return 27;
}

static uint32_t convert(const struct rf_bus *bus, uint32_t tables,
                        unsigned index, int16_t direction, uint16_t channel)
{
    uint16_t offset = (uint16_t)(channel - read16(bus, tables + 2 * index));
    uint16_t low = read16(bus, tables + (direction == 0 ? 0xa2 : 0xd8) + 2 * index);
    return UINT32_C(1000) * (offset + (low & UINT32_C(0x7fff)));
}

uint32_t rfad_channel_frequency(const struct rf_bus *bus, uint32_t tables,
                                int16_t direction, uint16_t channel)
{
    unsigned index = find_channel(bus, tables, channel);
    return convert(bus, tables, index == 27 ? 0 : index, direction, channel);
}

int rfad_channel_frequency_checked(const struct rf_bus *bus, uint32_t tables,
                                   unsigned direction, uint32_t channel,
                                   uint32_t output)
{
    if (direction > 1 || channel > UINT16_MAX)
        return -1;
    unsigned index = find_channel(bus, tables, (uint16_t)channel);
    if (index == 27)
        return -1;
    uint32_t frequency = convert(bus, tables, index, (int16_t)direction, (uint16_t)channel);
    bus->write(bus->context, output, frequency, 4);
    return 0;
}
