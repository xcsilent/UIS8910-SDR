#ifndef UIS8910_RF_FRONTEND_NV_H
#define UIS8910_RF_FRONTEND_NV_H
#include <stddef.h>
#include <stdint.h>

/* SDK rf_lte_nv.h DWARF, checked against native CP copy/command encoders.
 * This API decodes bytes only. It does not select a physical RF path or send
 * MIPI commands. nv_row is a sysctrl.band[] row, not an RF software selector. */
#define UIS8910_RFNV_BYTES 16384u
#define UIS8910_RFNV_BAND_ROWS 24u
#define UIS8910_RFNV_ANT_ROWS 4u
struct uis8910_mipi_nv_word {
    uint8_t reg_value, reg_addr, slave_id, reserved;
};
struct uis8910_gpo_nv_word { uint16_t mask, value; };
struct uis8910_rx_frontend_nv {
    struct uis8910_mipi_nv_word switch_open[4], switch_close[4];
    struct uis8910_mipi_nv_word lna_open[4], lna_close[4];
    struct uis8910_gpo_nv_word gpo_switch_open, gpo_switch_close;
    struct uis8910_gpo_nv_word gpo_lna_open, gpo_lna_close, gpo_rxtx, gpo_antenna;
    uint16_t mdll_enable, mdll_table_value;
    uint32_t gpo_open_command;
};
/* Returns -1 on an invalid argument, leaving *out unchanged. Zero MIPI words
 * are retained as raw entries; this decoder makes no bus-enable inference. */
int uis8910_read_rx_frontend_nv(const uint8_t *nv, size_t bytes,
    unsigned nv_row, unsigned antenna_row, struct uis8910_rx_frontend_nv *out);
#endif
