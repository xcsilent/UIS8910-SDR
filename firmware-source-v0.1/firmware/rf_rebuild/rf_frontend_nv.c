#include "rf_frontend_nv.h"

static uint16_t get16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}
static struct uis8910_gpo_nv_word gpo(const uint8_t *nv, unsigned base, unsigned row)
{
    struct uis8910_gpo_nv_word result;
    const uint8_t *p = nv + base + 4u * row;
    result.mask = get16(p); result.value = get16(p + 2);
    return result;
}
static void mipi(const uint8_t *nv, unsigned base, unsigned row,
                 struct uis8910_mipi_nv_word out[4])
{
    const uint8_t *p = nv + base + 16u * row;
    for (unsigned i = 0; i < 4u; ++i, p += 4) {
        out[i].reg_value = p[0]; out[i].reg_addr = p[1];
        out[i].slave_id = p[2]; out[i].reserved = p[3];
    }
}
int uis8910_read_rx_frontend_nv(const uint8_t *nv, size_t bytes,
    unsigned row, unsigned antenna, struct uis8910_rx_frontend_nv *out)
{
    struct uis8910_rx_frontend_nv r;
    uint32_t mask, value;
    if (!nv || !out || bytes < UIS8910_RFNV_BYTES ||
        row >= UIS8910_RFNV_BAND_ROWS || antenna >= UIS8910_RFNV_ANT_ROWS)
        return -1;
    mipi(nv, 0x0310u, row, r.switch_open);
    mipi(nv, 0x0490u, row, r.switch_close);
    mipi(nv, 0x0610u, row, r.lna_open);
    mipi(nv, 0x0790u, row, r.lna_close);
    r.gpo_switch_open = gpo(nv, 0x1428u, row);
    r.gpo_switch_close = gpo(nv, 0x1488u, row);
    r.gpo_lna_open = gpo(nv, 0x14e8u, row);
    r.gpo_lna_close = gpo(nv, 0x1548u, row);
    r.gpo_rxtx = gpo(nv, 0x17e8u, row);
    r.gpo_antenna = gpo(nv, 0x1910u, antenna);
    r.mdll_enable = get16(nv + 0x1270u);
    r.mdll_table_value = get16(nv + 0x1274u + 2u * row);
    mask = r.gpo_switch_open.mask | r.gpo_lna_open.mask |
           r.gpo_rxtx.mask | r.gpo_antenna.mask;
    value = r.gpo_switch_open.value | r.gpo_lna_open.value |
            r.gpo_rxtx.value | r.gpo_antenna.value;
    r.gpo_open_command = UINT32_C(0x440000) | ((value | (mask << 8)) & 0xffffu);
    /* Keep this reader usable in a freestanding RAM module without libc. */
    for (size_t i = 0; i < sizeof(r); ++i)
        ((uint8_t *)out)[i] = ((const uint8_t *)&r)[i];
    return 0;
}
