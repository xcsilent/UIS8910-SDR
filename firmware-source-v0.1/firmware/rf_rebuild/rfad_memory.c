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

static void load_events(const struct rf_bus *bus, uint32_t source,
                        uint32_t table, uint32_t destination)
{
    uint32_t index;
    for (index = 0; index < 152; ++index) {
        uint32_t record = source + 8 * index;
        uint32_t header = read32(bus, record);
        if (header & UINT32_C(0x000ff000)) {
            uint32_t kind = header & 15;
            uint32_t time = read16(bus, record + 4);
            uint32_t flags = (header >> 4) & 15;
            uint32_t link = 0;
            if (kind == 2 || kind == 3) {
                uint32_t first = read16(bus, table + 0x31e4 + 2 * index);
                /* The original uses LDRB at a UINT16 array element. Reading
                 * both bytes or normalizing the count would change behavior. */
                uint32_t count = bus->read(bus->context, table + 0x3314 + 2 * index, 1) & 0xff;
                link = (first | (count << 9)) & UINT32_C(0xffff);
            }
            write32(bus, destination, (flags << 30) | (time << 16) | (kind << 14) | link);
            destination += 4;
        }
    }
}

static void load_actions(const struct rf_bus *bus, uint32_t source, uint32_t destination)
{
    uint32_t index;
    for (index = 0; index < 200; ++index) {
        uint32_t record = source + 8 * index;
        uint32_t header = read32(bus, record);
        if (header & UINT32_C(0x000ff000)) {
            write32(bus, destination, read32(bus, record + 4));
            destination += 4;
        }
    }
}

void rfad_load_templates(const struct rf_bus *bus, uint32_t nv,
                         uint32_t down, uint32_t up)
{
    /* The two NV directions have 0xc00-byte records areas. Hardware bank
     * offsets remain fixed even when disabled records compact each area. */
    load_events(bus, nv + 0x20, down, RFAD_BASE + 0x1000);
    load_actions(bus, nv + 0x4e0, RFAD_BASE + 0x1260);
    load_events(bus, nv + 0xc20, up, RFAD_BASE + 0x2000);
    load_actions(bus, nv + 0x10e0, RFAD_BASE + 0x2260);
}

void rfad_initialize_memory(const struct rf_bus *bus,
                            const struct rfad_memory_context *context)
{
    uint32_t index;
    uint32_t saved;
    write32(bus, RFAD_BASE, 0);
    for (index = 0; index < 384; ++index) {
        write32(bus, RFAD_BASE + 0x1000 + 4 * index, UINT32_C(0xffffffff));
        write32(bus, RFAD_BASE + 0x2000 + 4 * index, UINT32_C(0xffffffff));
    }
    rfad_load_templates(bus, context->nv, context->down, context->up);
    saved = context->save_disable_irq(context->irq_context);
    write32(bus, RFAD_BASE, 3);
    context->restore_irq(context->irq_context, saved);
}
