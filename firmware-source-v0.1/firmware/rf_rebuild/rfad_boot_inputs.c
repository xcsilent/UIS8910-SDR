#include "rfad_boot_inputs.h"
#include "rfad_boot_memory.h"

int rfad_apply_boot_band_mask(const struct rf_bus *b, uint32_t nv,
                              uint32_t mask, const uint8_t map[32])
{
    if ((mask >> 24) != 0x5eu) return 1;
    mask &= 0xffffffu;
    for (unsigned row = 0; row < 24; ++row)
        b->write(b->context, nv + 0x1850u + 4u * row, 0, 2);
    for (unsigned bit = 0; bit < 24; ++bit) {
        if (!(mask & (1u << bit)) || !map[bit]) continue;
        for (unsigned row = 0; row < 24; ++row) {
            unsigned band = b->read(b->context, nv + 0x1820u + 2u * row, 2);
            if (map[bit] == 28u) {
                if (band == 650u || band == 651u)
                    b->write(b->context, nv + 0x1850u + 4u * row, 1, 2);
            } else if (band == map[bit]) {
                b->write(b->context, nv + 0x1850u + 4u * row, 1, 2);
                break;
            }
        }
    }
    return 0;
}

static int valid(uint32_t address, uint32_t size)
{
    return !(address & 3u) && address >= 0x80000000u &&
           address <= 0x80960000u && size <= 0x80960000u - address;
}

static int overlap(uint32_t a, uint32_t n, uint32_t b, uint32_t m)
{
    return a < b + m && b < a + n;
}

static int resolve_regions(const struct rf_bus *b, uint32_t regions[3][2])
{
    static const char *const names[3] = {
        "rf_nv.bin", "lte_rf_calib.bin", "gsm_rf_calib.bin"
    };
    static const uint32_t lengths[3] = {22528u, 32768u, 8192u};
    for (unsigned i = 0; i < 3; ++i) {
        int result = rfad_boot_get_memory(b, (uint32_t)(uintptr_t)names[i],
                                         (uint32_t)(uintptr_t)regions[i]);
        if (result) return RFAD_BOOT_INPUTS_MISSING;
        if (regions[i][1] != lengths[i]) return RFAD_BOOT_INPUTS_LAYOUT;
        if (!valid(regions[i][0], regions[i][1])) return RFAD_BOOT_INPUTS_RANGE;
        if (overlap(regions[i][0], regions[i][1], 0x8048355cu, 22528u) ||
            overlap(regions[i][0], regions[i][1], 0x80476710u, 8u) ||
            overlap(regions[i][0], regions[i][1], 0x80476730u, 8u))
            return RFAD_BOOT_INPUTS_RANGE;
        for (unsigned j = 0; j < i; ++j)
            if (overlap(regions[i][0], regions[i][1], regions[j][0], regions[j][1]))
                return RFAD_BOOT_INPUTS_RANGE;
    }
    return RFAD_BOOT_INPUTS_OK;
}

int rfad_validate_boot_inputs(const struct rf_bus *b)
{
    uint32_t regions[3][2];
    return resolve_regions(b, regions);
}

int rfad_restore_boot_inputs(const struct rf_bus *b, uint32_t mask,
                              const uint8_t map[32])
{
    uint32_t regions[3][2];
    int result = resolve_regions(b, regions);
    if (result) return result;
    for (uint32_t offset = 0; offset < 22528u; offset += 4u) {
        uint32_t value = b->read(b->context, regions[0][0] + offset, 4);
        b->write(b->context, 0x8048355cu + offset, value, 4);
    }
    (void)rfad_apply_boot_band_mask(b, 0x8048355cu, mask, map);
    for (unsigned i = 1; i < 3; ++i) {
        uint32_t cell = i == 1 ? 0x80476710u : 0x80476730u;
        b->write(b->context, cell, regions[i][0], 4);
        b->write(b->context, cell + 4u, regions[i][1], 4);
    }
    return RFAD_BOOT_INPUTS_OK;
}
