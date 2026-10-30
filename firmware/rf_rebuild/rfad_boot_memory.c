#include "rfad_boot_memory.h"

static int terminated_name(const struct rf_bus *b, uint32_t address, uint8_t name[20])
{
    for (unsigned i = 0; i < 20; ++i) {
        name[i] = (uint8_t)b->read(b->context, address + i, 1);
        if (!name[i]) return 1;
    }
    return 0;
}

int32_t rfad_boot_get_memory(const struct rf_bus *b, uint32_t query, uint32_t output)
{
    if (!query || !output) return RFAD_BOOT_MEMORY_INVALID;
    b->write(b->context, output, 0, 4);
    b->write(b->context, output + 4u, 0, 4);
    uint8_t key[20], name[20];
    if (!terminated_name(b, query, key)) return RFAD_BOOT_MEMORY_NAME;
    for (uint32_t index = 0; index < 64; ++index) {
        uint32_t entry = 0x80000000u + index * 32u;
        if (!terminated_name(b, entry, name)) return RFAD_BOOT_MEMORY_NAME;
        unsigned i = 0;
        while (key[i] == name[i] && key[i]) ++i;
        if (key[i] != name[i]) continue;
        uint32_t address = b->read(b->context, entry + 20u, 4);
        b->write(b->context, output, address, 4);
        uint32_t length = b->read(b->context, entry + 24u, 4);
        b->write(b->context, output + 4u, length, 4);
        return RFAD_BOOT_MEMORY_OK;
    }
    return RFAD_BOOT_MEMORY_MISSING;
}
