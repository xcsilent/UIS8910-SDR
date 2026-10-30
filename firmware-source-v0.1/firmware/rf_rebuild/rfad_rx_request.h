#ifndef UIS8910_RFAD_RX_REQUEST_H
#define UIS8910_RFAD_RX_REQUEST_H
#include <stdint.h>

/* Raw firmware fields, not calibrated Hz, microseconds or sample counts.
 * Supported subset: RX only, normal CP, one window contained within the
 * known 30720-unit calibration interval, mode 1 (LTED) or 2 (LTES).
 * Band/channel conversion and actual RF state remain caller dependencies. */
struct rfad_rx_request_config {
    uint32_t target_subframe;
    uint32_t mode;
    uint32_t band_indicator;
    uint32_t channel;
    uint32_t bandwidth_index;
    uint32_t gain;
    uint32_t card;
    uint32_t offset;
    uint32_t length;
};

struct rfad_rx_request_plan {
    uint32_t advanced_cycle;
    uint32_t advanced_ssfn;
    uint32_t selected_subframe;
    uint32_t mode1_stop_required;
    uint32_t mode1_end_cycle;
    uint32_t mode1_end_ssfn;
    uint32_t mode1_end_offset;
    uint32_t event_words[10]; /* l1cc2rf_event_info_t, 40 bytes */
    uint32_t rx_words[15];    /* l1cc2rf_rx_data_info_t, 60 bytes */
};

/* Returns 1 when the advanced local frame selects this RX window, 0 while
 * waiting, or -1 before modifying *out for an unsupported/invalid input.
 * Configuration and output must be distinct, valid objects. A valid call
 * always reports the (SSFN+2)%10240 time and its 16-bit cycle wrap.
 * This constructs packets ONLY. It never calls RF, MMIO, DMA, OS or L1.
 * Mode 1 additionally requires a verified end/stop operation; the metadata
 * below is not an implementation of rf_lte_event_stop or resource release. */
int rfad_rx_request_plan(const struct rfad_rx_request_config *,
                         struct rfad_rx_request_plan *,
                         uint32_t initial_cycle, uint32_t initial_ssfn);
#endif
