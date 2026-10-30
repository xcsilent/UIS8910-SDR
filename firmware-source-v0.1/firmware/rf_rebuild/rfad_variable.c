#include "rfad_variable.h"

static uint32_t rd(const struct rf_bus *b, uint32_t a, unsigned n)
{
    return b->read(b->context, a, n);
}

static void wr(const struct rf_bus *b, uint32_t a, uint32_t v, unsigned n)
{
    b->write(b->context, a, v, n);
}

static void fill16(const struct rf_bus *b, uint32_t a, uint32_t v, uint32_t count)
{
    for (uint32_t i = 0; i < count; ++i)
        wr(b, a + 2u * i, v, 2);
}

static void diagnostic(const struct rfad_variable_context *c, uint32_t kind,
                       const uint32_t *values, uint32_t count)
{
    if (c->diagnostic)
        c->diagnostic(c->diagnostic_context, kind, values, count);
}

void rfad_initialize_variables(const struct rf_bus *b,
                               const struct rfad_variable_context *c, uint32_t hwinit)
{
    uint32_t g = c->globals;
    uint32_t value = rd(b, c->rfnv + 0xd6u, 2);
    uint32_t mask = rd(b, c->rfnv + 0xd4u, 2);
    uint32_t gsm = rd(b, c->gsm_buffer_cell, 4);
    wr(b, g + 0x28u, value & mask, 4);
    wr(b, g + 0x2cu, value & mask, 4);
    uint32_t lte = rd(b, c->lte_buffer_cell, 4);
    wr(b, g + 0x38u, lte, 4);
    wr(b, g + 0x3cu, lte, 4);

    uint32_t flag = rd(b, lte + 2u, 2);
    uint32_t args[6];
    if (flag) {
        args[5] = rd(b, lte + 22u, 2);
        args[4] = rd(b, lte + 20u, 2);
        args[3] = rd(b, lte + 16u, 4);
        args[2] = rd(b, lte + 12u, 4);
        args[1] = rd(b, lte + 24u, 4);
        args[0] = rd(b, lte + 2u, 2);
        diagnostic(c, RFAD_DIAG_LTE_SPRD, args, 6);
    } else if (rd(b, lte + 16u, 2) == 0x5555u) {
        args[2] = rd(b, lte + 4u, 4);
        args[1] = rd(b, lte + 12u, 4);
        args[0] = rd(b, lte + 8u, 4);
        diagnostic(c, RFAD_DIAG_LTE_RDA, args, 3);
    } else {
        diagnostic(c, RFAD_DIAG_LTE_UNCALIBRATED, args, 0);
    }
    args[0] = rd(b, gsm + 0x1cecu, 4);
    diagnostic(c, args[0] ? RFAD_DIAG_GSM_CALIBRATED : RFAD_DIAG_GSM_UNCALIBRATED,
               args, args[0] ? 1u : 0u);

    wr(b, g + 0x24u, 0, 4);
    wr(b, g + 0x20u, 0, 4);
    wr(b, g, 0, 2);
    wr(b, g + 2u, 0, 2);
    wr(b, g + 4u, 1, 2);
    wr(b, g + 6u, 0, 2);
    wr(b, g + 8u, 1, 2);
    wr(b, g + 0x30u, 21400000u, 4);
    wr(b, g + 0x34u, 19500000u, 4);
    wr(b, g + 0xau, 0, 2);
    wr(b, g + 0xcu, 0, 2);
    wr(b, g + 0x14u, 0, 2);

    uint32_t table = rd(b, g + 0x38u, 4);
    uint32_t slope;
    if (rd(b, table + 2u, 2) & 1u) {
        wr(b, g + 0x40u, rd(b, table + 4u, 2), 2);
        wr(b, g + 0x42u, rd(b, table + 6u, 2), 2);
        slope = rd(b, table + 8u, 2);
    } else {
        table = rd(b, g + 0x3cu, 4);
        if (rd(b, table + 0x10u, 2) == 0x5555u &&
            rd(b, table + 0x3aa8u, 2) == 0xabcdu) {
            wr(b, g + 0x40u, rd(b, table + 0x3ab0u, 2), 2);
            wr(b, g + 0x42u, rd(b, table + 0x3ab2u, 2), 2);
            slope = rd(b, table + 0x3ab4u, 2);
        } else {
            wr(b, g + 0x40u, rd(b, c->cdac, 2), 2);
            wr(b, g + 0x42u, rd(b, c->rfnv + 0xeau, 2), 2);
            slope = rd(b, c->rfnv + 0xecu, 2);
        }
    }
    wr(b, g + 0x44u, slope, 2);

    uint32_t info = g + 0x120u;
    wr(b, info, 1, 2);
    wr(b, info + 4u, 0, 2);
    wr(b, info + 8u, 1, 2);
    wr(b, info + 28u, 21400000u, 4);
    wr(b, info + 32u, 19500000u, 4);
    wr(b, info + 36u, 0, 2);
    wr(b, info + 38u, 0, 2);
    wr(b, info + 40u, 2, 2);
    fill16(b, g + 0x14cu, 0, 8);
    fill16(b, g + 0x15cu, 0, 8);
    fill16(b, g + 0x16cu, 0, 20);
    fill16(b, g + 0x194u, 0, 12);
    fill16(b, g + 0x2a8u, 0, 6);
    fill16(b, g + 0x1e0u, 0, 100);
    fill16(b, g + 0x1acu, 0, 26);
    fill16(b, g + 0x48u, 0xffffu, 72);

    wr(b, g + 0x16cu + 12u, rd(b, info + 28u, 4), 4);
    wr(b, g + 0x194u + 12u, rd(b, info + 32u, 4), 4);
    wr(b, g + 0x16cu + 30u, 0xffffu, 2);
    wr(b, g + 0x16cu + 28u, rd(b, info + 36u, 2), 2);
    wr(b, g + 0x194u + 16u, rd(b, info + 38u, 2), 2);
    wr(b, g + 0x104u, 0, 4);
    wr(b, g + 0x108u, 0, 4);
    wr(b, g + 0x10cu, 0, 4);
    wr(b, c->fdidle, 0, 2);
    wr(b, g + 0xeu, 0, 2);
    wr(b, g + 0xdau, 0, 2);
    wr(b, g + 0xdcu, 0, 2);
    wr(b, g + 0x10u, 0, 2);
    wr(b, g + 0x12u, 0, 2);
    wr(b, g + 0xdeu, 0, 2);
    wr(b, c->framelen, 0x7800u, 4);
    wr(b, c->framelen + 4u, 0x7800u, 4);
    wr(b, g + 0xe0u, 0, 2);
    wr(b, g + 0xe2u, 1, 2);
    wr(b, g + 0xe4u, 0, 2);
    wr(b, g + 0xe6u, 0, 2);
    wr(b, g + 0x110u, 0, 4);
    wr(b, g + 0xeau, 0, 2);
    wr(b, g + 0xecu, 0, 2);
    wr(b, g + 0x118u, 0, 4);
    wr(b, g + 0x11cu, 0, 4);
    wr(b, g + 0xf0u, 0, 2);
    wr(b, g + 0xf2u, 0, 2);
    wr(b, g + 0xf4u, 0, 2);
    wr(b, g + 0xf6u, 0, 2);
    wr(b, g + 0xfeu, 0, 2);
    wr(b, g + 0xf8u, 0, 2);
    wr(b, g + 0xfau, 0, 2);
    wr(b, g + 0xfcu, 0, 2);
    wr(b, g + 0x102u, 0, 2);
    if (hwinit) {
        wr(b, c->afc_flag, 1, 2);
        uint32_t fof = rd(b, c->fof_back, 4);
        wr(b, c->fof_pair, fof, 4);
        wr(b, c->fof_pair + 4u, fof, 4);
    }
    wr(b, g + 0x18u, 0x25101580u, 4);
    wr(b, g + 0x1cu, 0x25102580u, 4);
}
