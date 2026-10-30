#include "rfad_rx_window.h"

static uint32_t rd(const struct rf_bus *b, uint32_t a, unsigned n) {
    return b->read(b->context, a, n);
}
static void wr(const struct rf_bus *b, uint32_t a, uint32_t v, unsigned n) {
    b->write(b->context, a, v, n);
}
static uint32_t slot(const struct rf_bus *b, const struct rfad_calib_rx_context *c) {
    return c->subframes + 56u * rd(b, c->calibration + 0xd0u, 2);
}

void rfad_calib_rx_configure(const struct rf_bus *b, const struct rfad_calib_rx_context *c) {
    uint32_t v, arfcn, indicator;
    wr(b, slot(b, c), 1, 2);
    v = rd(b, c->calibration + 0x92u, 2); wr(b, slot(b, c) + 8, v, 2);
    v = rd(b, c->calibration + 0x98u, 2); wr(b, slot(b, c) + 10, v, 2);
    v = rd(b, c->calibration + 0x9au, 2); wr(b, slot(b, c) + 12, v, 2);
    v = rd(b, c->calibration + 0xd2u, 2); wr(b, slot(b, c) + 14, v, 2);
    v = rd(b, c->calibration + 0xd4u, 2); wr(b, slot(b, c) + 16, v, 2);
    v = rd(b, c->calibration + 0xd8u, 4); wr(b, slot(b, c) + 24, v, 4);
    v = rd(b, c->calibration + 0xdeu, 2); wr(b, slot(b, c) + 30, v, 2);
    indicator = rd(b, c->calibration + 0x92u, 2);
    arfcn = rd(b, c->calibration + 0x98u, 2);
    c->set_frequency(c->frequency_context, arfcn, indicator);
    uint32_t destination = slot(b, c);
    v = rd(b, c->rf_info, 2); wr(b, destination + 2, v, 2);
    destination = slot(b, c);
    v = rd(b, c->rf_info + 0x1cu, 4); wr(b, destination + 4, v, 4);
}

void rfad_rx_first_ofdm_offset(const struct rf_bus *b, uint32_t offset) {
    uint32_t config = rd(b, UINT32_C(0x25000020), 4);
    uint32_t previous = rd(b, UINT32_C(0x25000024), 4);
    wr(b, UINT32_C(0x25000020), config | UINT32_C(0x00200000), 4);
    wr(b, UINT32_C(0x25000024), (previous & ~UINT32_C(0x3ff)) | (offset & 0x3ffu), 4);
}
