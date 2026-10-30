#include "rfad.h"

static uint32_t read32(const struct rf_bus *bus, uint32_t address)
{
    return bus->read(bus->context, address, 4);
}

static uint32_t read16(const struct rf_bus *bus, uint32_t address)
{
    return bus->read(bus->context, address, 2) & UINT32_C(0xffff);
}

static void write32(const struct rf_bus *bus, uint32_t address, uint32_t value)
{
    bus->write(bus->context, address, value, 4);
}

void rfad_event_valid(const struct rf_bus *bus, uint32_t event)
{
    write32(bus, event, read32(bus, event) | RFAD_EVENT_VALID);
}

void rfad_event_invalid(const struct rf_bus *bus, uint32_t event)
{
    write32(bus, event, read32(bus, event) & ~RFAD_EVENT_VALID);
}

void rfad_event_invalid_end(const struct rf_bus *bus, uint32_t event)
{
    write32(bus, event, (read32(bus, event) & ~RFAD_EVENT_VALID) | RFAD_EVENT_END);
}

void rfad_event_data_modify(const struct rf_bus *bus, uint32_t event, uint32_t data)
{
    /* The original clears bits 0..13, then ORs ALL input bits. Masking data
     * here would silently change vendor behavior for noncanonical input. */
    uint32_t word = read32(bus, event) & ~UINT32_C(0x3fff);
    write32(bus, event, word | data);
}

void rfad_rx_frequency(const struct rf_bus *bus, uint32_t slots, uint32_t rx_info)
{
    uint32_t destination = read32(bus, slots + 0x10);
    uint32_t frequency = read16(bus, rx_info + 12);
    write32(bus, destination, frequency | UINT32_C(0x01100000));
    destination = read32(bus, slots + 0x14);
    frequency = read32(bus, rx_info + 12);
    write32(bus, destination, (frequency >> 16) | UINT32_C(0x01140000));
    destination = read32(bus, slots + 0x0c);
    write32(bus, destination, UINT32_C(0x00280001));
}

void rfad_rxon_frequency(const struct rf_bus *bus, uint32_t slots, uint32_t rx_info)
{
    uint32_t destination = read32(bus, slots + 0x10);
    uint32_t frequency = read16(bus, rx_info + 12);
    write32(bus, destination, frequency | UINT32_C(0x00580000));
    destination = read32(bus, slots + 0x14);
    frequency = read32(bus, rx_info + 12);
    write32(bus, destination, (frequency >> 16) | UINT32_C(0x00080000));
}

int rfad_configure_controller(const struct rf_bus *bus, uint32_t rfnv)
{
    uint32_t gpo_value;
    uint32_t gpo_mask;
    if (read32(bus, UINT32_C(0x500a0024)) != 3)
        return -1;
    if (read32(bus, UINT32_C(0x500a0028)) != 3)
        return -1;

    write32(bus, RFAD_BASE + 4, UINT32_C(0x60986098));
    write32(bus, RFAD_BASE + 0x10, read32(bus, rfnv + 0xc4));
    gpo_value = read16(bus, rfnv + 0xd6);
    gpo_mask = read16(bus, rfnv + 0xd4);
    /* Hex-Rays merges these two stores; both exist in the shipped ARM. */
    write32(bus, RFAD_BASE + 8, gpo_value & gpo_mask);
    write32(bus, RFAD_BASE + 8, (gpo_value & gpo_mask) | UINT32_C(0x10000));
    write32(bus, RFAD_BASE, 0);
    write32(bus, UINT32_C(0x50080020), read32(bus, rfnv + 0xb0));
    write32(bus, UINT32_C(0x50080024), read32(bus, rfnv + 0xb4));
    return 0;
}

void rfad_bind_ram1(const struct rf_bus *bus, uint32_t config,
                   uint32_t nv_action, uint32_t command)
{
    uint32_t slot;
    uint32_t action = (read32(bus, nv_action) >> 12) & 0xff;
    switch (action) {
    case 3: slot = 2; break;  /* gporeset */
    case 4: slot = 3; break;  /* gpofill */
    case 9:
        /* The original deliberately binds both LTE and GGE path slots. */
        write32(bus, config + 16, command);
        write32(bus, config + 76, nv_action);
        slot = 5;
        break;
    case 10: slot = 5; break;
    case 11: slot = 6; break; /* adon */
    case 12: slot = 7; break; /* rxon */
    case 13: slot = 8; break; /* gpolna */
    case 16: slot = 9; break;
    case 17: slot = 10; break;
    case 18: slot = 11; break;
    case 19: slot = 12; break;
    case 20: slot = 13; break;
    case 21: slot = 14; break;
    default: return;
    }
    write32(bus, config + 4 * slot, command);
    write32(bus, config + 60 + 4 * slot, nv_action);
}

void rfad_bind_ram2(const struct rf_bus *bus, uint32_t config,
                   uint32_t nv_action, uint32_t command, uint16_t ram1_index)
{
    uint32_t slot;
    uint32_t action = (read32(bus, nv_action) >> 12) & 0xff;
    switch (action) {
    case 31: slot = 2; break;  /* xcvr_bandbw */
    case 33: slot = 3; break;  /* xcvr_freqc */
    case 34: slot = 4; break;  /* xcvr_freql */
    case 35: slot = 5; break;  /* xcvr_freqh */
    case 36: slot = 6; break;  /* xcvr_agc */
    case 38: slot = 7; break;
    case 39: slot = 8; break;
    case 40: slot = 9; break;
    case 42: slot = 1; break;  /* spi_fill */
    case 43: slot = 10; break;
    case 50: case 51: case 52: case 53: case 54:
        slot = 11 + action - 50; break; /* mipi_sw1..5 */
    case 60: case 61: case 62: case 63: case 64:
        slot = 16 + action - 60; break; /* mipi_lna1..5 */
    case 80: case 81: case 82: case 83: case 84:
        slot = 21 + action - 80; break; /* mipi_pa1..5 */
    case 89: slot = 26; break;
    case 106: slot = 27; break;
    case 107: slot = 30; break; /* agc_nodci precedes freql in action IDs */
    case 108: slot = 28; break;
    case 109: slot = 29; break;
    case 110: slot = 31; break;
    case 111: slot = 32; break;
    default: return;
    }
    bus->write(bus->context, config + 132 + 2 * slot, ram1_index, 2);
    write32(bus, config + 4 * slot, command);
}
