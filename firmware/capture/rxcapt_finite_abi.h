#ifndef RXCAPT_FINITE_ABI_H
#define RXCAPT_FINITE_ABI_H

#include <stdint.h>

#define RXCAPT_FINITE_MAGIC 0x52434631u
#define RXCAPT_FINITE_SNAPSHOT_WORDS 128u
/* AP/CP must be built with matching output geometry. Default is the deployed
 * seven-slot ABI; non-default values are for isolated experiments only. */
#ifndef SDR_RX_OUTPUT_SLOTS
#define SDR_RX_OUTPUT_SLOTS 7u
#endif
#if SDR_RX_OUTPUT_SLOTS < 2u || SDR_RX_OUTPUT_SLOTS > 7u
#error invalid SDR output slot count
#endif
#ifndef RXCAPT_FINITE_DATA_BYTES
#define RXCAPT_FINITE_DATA_BYTES 8000u
#endif
#ifndef RXCAPT_FINITE_CAPTURE_END_ADDRESS
#define RXCAPT_FINITE_CAPTURE_END_ADDRESS 1999u
#endif
#if RXCAPT_FINITE_DATA_BYTES != (RXCAPT_FINITE_CAPTURE_END_ADDRESS + 1u) * 4u
#error RXCAPT data bytes and capture end address must describe the same samples
#endif
#if RXCAPT_FINITE_DATA_BYTES == 0 || RXCAPT_FINITE_DATA_BYTES % 32u
#error RXCAPT data slots must contain complete 32-byte cache lines
#endif

enum {
    RXCAPT_PHASE_EMPTY = 0,
    RXCAPT_PHASE_PREPARING = 1,
    RXCAPT_PHASE_PREPARED = 2,
    RXCAPT_PHASE_RUNNING = 3,
    RXCAPT_PHASE_COMPLETE = 4,
    RXCAPT_PHASE_STOPPING = 5,
    RXCAPT_PHASE_HELD = 6,
    RXCAPT_PHASE_ABORTED = 7,
    RXCAPT_PHASE_PINNED = 8,
    RXCAPT_PHASE_FAILED = 9,
    RXCAPT_PHASE_REJECTED = 10
};

enum {
    RXCAPT_CMD_MAGIC = 0x2000,
    RXCAPT_CMD_PREPARE = 0x2001,
    RXCAPT_CMD_ARM = 0x2002,
    RXCAPT_CMD_FINISH = 0x2003,
    RXCAPT_CMD_ABORT = 0x2004,
    RXCAPT_CMD_SNAPSHOT = 0x2005,
    RXCAPT_CMD_INIT_AND_ARM = 0x200d
};

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t phase;
    uint32_t error;
    uint32_t done_mask;
    uint32_t data_channel;
    uint32_t head_channel;
    uint32_t data_restore_callback;
    uint32_t head_restore_callback;
    uint32_t data_vendor_callback;
    uint32_t head_vendor_callback;
    uint32_t data_event_mask;
    uint32_t head_event_mask;
    uint32_t data_callback_count;
    uint32_t head_callback_count;
    uint32_t data_valid_bytes;
    uint32_t head_valid_bytes;
    uint32_t data_observed_bytes;
    uint32_t head_observed_bytes;
    uint32_t data_dma_status;
    uint32_t head_dma_status;
    uint32_t candidate_end_address;
    uint32_t data_stop_polls;
    uint32_t head_stop_polls;
    uint32_t saved_rxcap_en;
    uint32_t saved_capt_cfg;
    uint32_t saved_dma_req_en;
    uint32_t saved_capt_end_address;
    uint32_t saved_rxcap_globals[4];
    uint32_t saved_rxcap_dmach;
    uint32_t saved_capture_bitmap;
    uint32_t saved_dma_allocator_bitmap;
    uint32_t saved_rxcap_block_num;
    uint32_t saved_capture_table[8];
    uint32_t saved_data_descriptor[11];
    uint32_t saved_head_descriptor[11];
    uint32_t saved_dma_entries_7_9[6];
    uint32_t restored_rxcap_en;
    uint32_t restored_capt_cfg;
    uint32_t restored_dma_req_en;
    uint32_t restored_capt_end_address;
    uint32_t restored_dma_allocator_bitmap;
    uint32_t restored_data_callback;
    uint32_t restored_head_callback;
    uint32_t restored_dma_irq_status;
    uint32_t restored_data_conf;
    uint32_t restored_head_conf;
    uint32_t restored_data_status;
    uint32_t restored_head_status;
    uint32_t restored_data_map;
    uint32_t restored_head_map;
    uint32_t restored_data_count;
    uint32_t restored_head_count;
    uint32_t preflight_dma_req_sel_22000018;
    uint32_t preflight_dma_req_sel_2200001c;
    uint32_t saved_txrx_sys_cfg;
    uint32_t saved_txrx_stop_cfg;
    uint32_t saved_txrx_rx_cfg;
    uint32_t saved_txrx_rx_pre_cfg;
    uint32_t configured_rx_pre_cfg;
    uint32_t configured_rx_sys_cfg;
    uint32_t configured_rx_cfg;
    uint32_t configured_rx_stop_cfg;
    uint32_t observed_rx_ofdm_stat;
    uint32_t observed_rx_err_stat;
    uint32_t observed_rx_out_cfg;
    uint32_t observed_st_cnt_framc;
    uint32_t restored_txrx_sys_cfg;
    uint32_t restored_txrx_stop_cfg;
    uint32_t restored_txrx_rx_cfg;
    uint32_t restored_txrx_rx_pre_cfg;
    uint32_t rx_bandwidth_index;
} rxcapt_finite_state_t;

#endif
