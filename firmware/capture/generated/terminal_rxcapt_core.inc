#include <stdint.h>
#include "rxcapt_rx_pre_profile.h"

#define STATE ((volatile rxcapt_finite_state_t *)RXCAPT_FINITE_STATE_ADDRESS)
#define REG32(a) (*(volatile uint32_t *)(a))
#define DMA_ALLOC16 ((volatile uint16_t *)(RXCAPT_DMA_ALLOCATOR_ADDRESS + 2u))
#define DMA_CONSTRAINT16 ((volatile uint16_t *)RXCAPT_DMA_ALLOCATOR_ADDRESS)
#define DMA_IRQ_MASK REG32(0x2200000cu)
#define DMA_REQ_SEL_7_8 REG32(RXCAPT_DMA_REQ_SEL_WORD_7_8)
#define DMA_REQ_SEL_8_9 REG32(RXCAPT_DMA_REQ_SEL_WORD_8_9)
#define RXCAPT_REGS ((volatile uint32_t *)0x27000000u)
#define TXRX_REGS ((volatile uint32_t *)RXCAPT_TXRX_REGS_ADDRESS)
#define DMA_RUN_MASK 0x00000001u
#define DMA_INTERRUPT_STATUS_MASK 0x0000000eu
#define DMA_COUNT_FINISH_STATUS 0x00200000u
#define DMA_RESPONSE_ERROR_MASK 0x06000000u
#define DMA_CHANNEL_COUNT 12u
#define RXCAPT_DATA_WINDOW_BYTES RXCAPT_FINITE_DATA_BYTES
#define RXCAPT_HEAD_WINDOW_BYTES 24u
#define RXCAPT_RING_BLOCKS 7u
#define RXCAPT_RING_DATA_TOTAL_BYTES (RXCAPT_DATA_WINDOW_BYTES * RXCAPT_RING_BLOCKS)
#define RXCAPT_RING_HEAD_TOTAL_BYTES (RXCAPT_HEAD_WINDOW_BYTES * RXCAPT_RING_BLOCKS)

typedef void (*rxcap_card_fn)(uint32_t);
typedef void (*rxcap_release_fn)(uint32_t);
typedef void (*rxcap_lps_fn)(uint32_t, uint32_t);
typedef uint32_t (*rxcap_alloc_fn)(uint32_t);
typedef void (*rxcap_dma_start_fn)(uint32_t, uint32_t, const uint32_t *);

static void progress_clean(void) {
    for (uint32_t line = RXCAPT_FINITE_PROGRESS_ADDRESS;
         line < RXCAPT_FINITE_PROGRESS_ADDRESS + 64u; line += 32u)
        __asm__ volatile("mcr p15,0,%0,c7,c10,1" :: "r"(line) : "memory");
    __asm__ volatile("dsb sy" ::: "memory");
}

static void progress(uint32_t stage, uint32_t next, uint32_t detail);

static void publish_power_snapshot(uint32_t stage, uint32_t next,
                                   uint32_t detail, uint32_t zsp,
                                   uint32_t phy) {
    progress(stage, next, detail);
    volatile uint32_t *p =
        (volatile uint32_t *)RXCAPT_FINITE_PROGRESS_ADDRESS;
    uint32_t sequence = p[2] + 2u;
    p[2] = sequence | 1u;
    __asm__ volatile("dmb sy" ::: "memory");
    p[11] = zsp;
    p[12] = phy;
    p[13] = 0x50575231u;
    __asm__ volatile("dmb sy" ::: "memory");
    p[2] = sequence;
    progress_clean();
}

/* The monitor intentionally excludes CP debug scratch from AP reads. Publish
   a small record in the backed-up gap before HEAD instead, with cache clean
   before each potentially stalling access. This is diagnostic state only;
   an even sequence does not certify hardware readiness or DMA completion. */
static void progress(uint32_t stage, uint32_t next, uint32_t detail) {
    volatile uint32_t *p =
        (volatile uint32_t *)RXCAPT_FINITE_PROGRESS_ADDRESS;
    uint32_t sequence = p[0] == 0x52435031u ? (p[2] + 2u) & ~1u : 2u;
    uint32_t cpsr;
    __asm__ volatile("mrs %0,cpsr" : "=r"(cpsr));
    p[2] = sequence | 1u;
    __asm__ volatile("dmb sy" ::: "memory");
    p[0] = 0x52435031u;
    p[1] = 1u;
    p[3] = stage;
    p[4] = next;
    p[5] = detail;
    p[6] = STATE->phase;
    p[7] = STATE->error;
    p[8] = STATE->data_channel;
    p[9] = STATE->head_channel;
    p[10] = cpsr;
    if (stage == 5u)
        for (uint32_t i = 11; i < 16; ++i) p[i] = 0u;
    __asm__ volatile("dmb sy" ::: "memory");
    p[2] = sequence;
    progress_clean();
}

/* Read the always-on status words used by the bound vendor power-open
   routines. This does not request power, change constraints, or prove RF
   tuning; it refuses an IP access when its domain is already visibly off. */
static int domains_ready(void) {
    progress(5u, 0x500a0024u, 0u);
    uint32_t zsp = REG32(0x500a0024u);
    progress(6u, 0x500a0028u, zsp);
    uint32_t phy = REG32(0x500a0028u);
    publish_power_snapshot(7u, 0u, 0u, zsp, phy);
    return zsp == 3u && phy == 3u;
}

/* One-shot normal HAL power open for the LTE PHY domain. This intentionally
   leaves the vendor sleep constraint held. It never touches RXCAPT or DMA. */
static uint32_t open_lte_phy_domain(void) {
    uint32_t before = REG32(0x500a0028u);
    if (before != 2u && before != 3u) {
        uint32_t zsp = REG32(0x500a0024u);
        publish_power_snapshot(92u, RXCAPT_LTE_PHY_OPEN_ENTRY, before,
                               zsp, before);
        return 0x420u;
    }
    progress(90u, RXCAPT_LTE_PHY_OPEN_ENTRY, before);
    ((void (*)(void))RXCAPT_LTE_PHY_OPEN_ENTRY)();
    uint32_t zsp = REG32(0x500a0024u);
    uint32_t phy = REG32(0x500a0028u);
    publish_power_snapshot(91u, RXCAPT_LTE_PHY_OPEN_ENTRY, before,
                           zsp, phy);
    return phy == 3u ? 1u : 0x421u;
}

/* The debug monitor can run while both CP power domains are in state 2,
   unlike the normal L1 task. Open ZSP first, then the LTE PHY, using only the
   exact-bound vendor entry points and a fresh always-on status snapshot. */
static uint32_t open_lte_power_domains(void) { return terminal_open_domains(); }

/* Isolated bus-read probe: make the PHY domain ready through the exact-bound
   vendor open routine, then perform one read of the RXCAPT base register.
   No RXCAPT control register, DMA channel, request selector, or data buffer is
   written. Progress 95 is published before the potentially faulting read. */
static uint32_t probe_rxcapt_base_read(void) {
    uint32_t zsp = REG32(0x500a0024u);
    uint32_t phy = REG32(0x500a0028u);
    if (phy != 2u && phy != 3u) {
        publish_power_snapshot(94u, 0x27000000u, phy, zsp, phy);
        return 0x420u;
    }
    if (phy == 2u) {
        uint32_t opened = open_lte_phy_domain();
        if (opened != 1u) {
            zsp = REG32(0x500a0024u);
            phy = REG32(0x500a0028u);
            publish_power_snapshot(94u, 0x27000000u, opened, zsp, phy);
            return opened;
        }
    }
    zsp = REG32(0x500a0024u);
    phy = REG32(0x500a0028u);
    if (phy != 3u) {
        publish_power_snapshot(94u, 0x27000000u, phy, zsp, phy);
        return 0x421u;
    }
    publish_power_snapshot(93u, RXCAPT_LTE_AUTOGATE_CLEAR_ENTRY,
                           0xffffu, zsp, phy);
    ((void (*)(uint32_t))RXCAPT_LTE_AUTOGATE_CLEAR_ENTRY)(0xffffu);
    progress(95u, 0x27000000u, 0u);
    uint32_t value = REG32(0x27000000u);
    ((void (*)(void))RXCAPT_LTE_AUTOGATE_INIT_ENTRY)();
    zsp = REG32(0x500a0024u);
    phy = REG32(0x500a0028u);
    publish_power_snapshot(96u, 0x27000000u, value, zsp, phy);
    return 1u;
}

static uint32_t probe_rxcapt_with_both_domains(void) {
    uint32_t opened = open_lte_power_domains();
    if (opened != 1u) return opened;
    uint32_t zsp = REG32(0x500a0024u);
    uint32_t phy = REG32(0x500a0028u);
    publish_power_snapshot(84u, RXCAPT_LTE_AUTOGATE_CLEAR_ENTRY,
                           0xffffu, zsp, phy);
    ((void (*)(uint32_t))RXCAPT_LTE_AUTOGATE_CLEAR_ENTRY)(0xffffu);
    progress(85u, 0x27000000u, 0u);
    uint32_t value = REG32(0x27000000u);
    ((void (*)(void))RXCAPT_LTE_AUTOGATE_INIT_ENTRY)();
    zsp = REG32(0x500a0024u);
    phy = REG32(0x500a0028u);
    publish_power_snapshot(86u, 0x27000000u, value, zsp, phy);
    return zsp == 3u && phy == 3u ? 1u : 0x431u;
}

/* Run the vendor's normal LTE PHY wake path (including its native L1/RF init
   branch), then make one isolated RXCAPT base read. The path configures the
   separate IDDET SG-DMA/IRQ infrastructure, but this command never starts
   RXCAPT capture or the RXCAPT DATA/HEAD DMA channels. */
static void publish_wake_inputs(uint32_t sleep_state, uint32_t lps_lte2,
                                uint32_t initial_phy) {
    volatile uint32_t *p =
        (volatile uint32_t *)RXCAPT_FINITE_PROGRESS_ADDRESS;
    uint32_t sequence = (p[2] + 2u) & ~1u;
    p[2] = sequence | 1u;
    __asm__ volatile("dmb sy" ::: "memory");
    p[14] = sleep_state;
    p[15] = (lps_lte2 & 0xffu) | ((initial_phy & 0xffu) << 8);
    __asm__ volatile("dmb sy" ::: "memory");
    p[2] = sequence;
    progress_clean();
}

static uint32_t normal_lte_phy_wake_and_probe(void) {
    uint32_t sleep_state = REG32(0x80476ca0u);
    uint32_t lps_lte2 = (REG32(0x80476e40u) >> 8) & 0xffu;
    uint32_t phy = REG32(0x500a0028u);
    uint32_t detail = ((sleep_state & 0xffu) << 16) |
                      ((lps_lte2 & 0xffu) << 8) | (phy & 0xffu);
    publish_wake_inputs(sleep_state, lps_lte2, phy);
    if (phy == 3u && !(sleep_state == 3u && lps_lte2 == 3u)) {
        uint32_t zsp = REG32(0x500a0024u);
        publish_power_snapshot(98u, 0x27000000u, detail, zsp, phy);
        return 0x423u;
    }
    progress(97u, RXCAPT_LTE_PHY_WAKE_ENTRY, detail);
    ((void (*)(void))RXCAPT_LTE_PHY_WAKE_ENTRY)();

    uint32_t zsp = REG32(0x500a0024u);
    phy = REG32(0x500a0028u);
    publish_power_snapshot(98u, 0x27000000u, detail, zsp, phy);
    if (phy != 3u) return 0x421u;

    progress(99u, 0x27000000u, detail);
    uint32_t value = REG32(0x27000000u);
    zsp = REG32(0x500a0024u);
    phy = REG32(0x500a0028u);
    publish_power_snapshot(100u, 0x27000000u, value, zsp, phy);
    return phy == 3u ? 1u : 0x421u;
}

/* Instrument the two native calls separately so AP-only progress can tell
   whether the L1 hardware initializer or the RF init branch is the wait
   point. The sequence mirrors hal_LpsActLtePhy for the selected LPS state. */
static uint32_t staged_native_phy_init_and_probe(void) {
    uint32_t sleep_state = REG32(0x80476ca0u);
    uint32_t lps_lte2 = (REG32(0x80476e40u) >> 8) & 0xffu;
    uint32_t zsp = REG32(0x500a0024u);
    uint32_t phy = REG32(0x500a0028u);
    uint32_t detail = ((sleep_state & 0xffu) << 16) |
                      ((lps_lte2 & 0xffu) << 8) | (phy & 0xffu);
    publish_wake_inputs(sleep_state, lps_lte2, phy);

    if (phy == 3u && !(sleep_state == 3u && lps_lte2 == 3u)) {
        publish_power_snapshot(100u, 0x27000000u, detail, zsp, phy);
        return 0x423u;
    }
    uint32_t opened = open_lte_power_domains();
    if (opened != 1u) {
        zsp = REG32(0x500a0024u);
        phy = REG32(0x500a0028u);
        publish_power_snapshot(100u, RXCAPT_LTE_ZSP_OPEN_ENTRY,
                               opened, zsp, phy);
        return opened;
    }

    progress(101u, RXCAPT_LTE_PHY_INIT_ENTRY, detail);
    ((void (*)(void))RXCAPT_LTE_PHY_INIT_ENTRY)();
    zsp = REG32(0x500a0024u);
    phy = REG32(0x500a0028u);
    publish_power_snapshot(102u, 0x27000000u, detail, zsp, phy);
    if (phy != 3u) return 0x421u;

    uint32_t rf_entry = RXCAPT_RF_LTE_INIT_DYLOAD_ENTRY;
    progress(103u, rf_entry, detail);
    ((void (*)(void))rf_entry)();
    zsp = REG32(0x500a0024u);
    phy = REG32(0x500a0028u);
    publish_power_snapshot(104u, 0x27000000u, detail, zsp, phy);
    if (phy != 3u) return 0x421u;

    progress(105u, 0x27000000u, detail);
    uint32_t value = REG32(0x27000000u);
    zsp = REG32(0x500a0024u);
    phy = REG32(0x500a0028u);
    publish_power_snapshot(106u, 0x27000000u, value, zsp, phy);
    return phy == 3u ? 1u : 0x421u;
}

/* Rebuild the RF-relevant, finite hardware setup portion of the native L1
   init without its IDDET SG-DMA setup, measurement-power setup, or IRQ enable
   phase. Each vendor call is separated by AP-readable progress. */
static uint32_t isolated_phy_hw_init_and_probe(void) {
    uint32_t sleep_state = REG32(0x80476ca0u);
    uint32_t lps_lte2 = (REG32(0x80476e40u) >> 8) & 0xffu;
    uint32_t zsp = REG32(0x500a0024u);
    uint32_t phy = REG32(0x500a0028u);
    uint32_t detail = ((sleep_state & 0xffu) << 16) |
                      ((lps_lte2 & 0xffu) << 8) | (phy & 0xffu);
    publish_wake_inputs(sleep_state, lps_lte2, phy);
    uint32_t opened = open_lte_power_domains();
    if (opened != 1u) {
        zsp = REG32(0x500a0024u);
        phy = REG32(0x500a0028u);
        publish_power_snapshot(100u, RXCAPT_LTE_ZSP_OPEN_ENTRY,
                               opened, zsp, phy);
        return opened;
    }
    zsp = REG32(0x500a0024u);
    phy = REG32(0x500a0028u);
    if (phy != 3u) {
        publish_power_snapshot(100u, RXCAPT_LTE_AUTOGATE_CLEAR_ENTRY,
                               phy, zsp, phy);
        return 0x421u;
    }

    publish_power_snapshot(110u, RXCAPT_LTE_AUTOGATE_CLEAR_ENTRY,
                           0xffffu, zsp, phy);
    ((void (*)(uint32_t))RXCAPT_LTE_AUTOGATE_CLEAR_ENTRY)(0xffffu);
    progress(111u, RXCAPT_TXRX_SYS_INIT_ENTRY, detail);
    ((void (*)(void))RXCAPT_TXRX_SYS_INIT_ENTRY)();
    progress(112u, RXCAPT_DLFFT_SYS_INIT_ENTRY, detail);
    ((void (*)(void))RXCAPT_DLFFT_SYS_INIT_ENTRY)();
    progress(113u, RXCAPT_LDTC_SYS_INIT_ENTRY, detail);
    ((void (*)(void))RXCAPT_LDTC_SYS_INIT_ENTRY)();
    progress(114u, RXCAPT_RX_FIR_INIT_ENTRY, detail);
    ((void (*)(void))RXCAPT_RX_FIR_INIT_ENTRY)();
    progress(115u, RXCAPT_LTE_AUTOGATE_INIT_ENTRY, detail);
    ((void (*)(void))RXCAPT_LTE_AUTOGATE_INIT_ENTRY)();

    uint32_t rf_entry = RXCAPT_RF_LTE_INIT_DYLOAD_ENTRY;
    progress(116u, rf_entry, detail);
    ((void (*)(void))rf_entry)();
    zsp = REG32(0x500a0024u);
    phy = REG32(0x500a0028u);
    publish_power_snapshot(117u, 0x27000000u, detail, zsp, phy);
    if (phy != 3u) return 0x421u;

    progress(118u, 0x27000000u, detail);
    uint32_t value = REG32(0x27000000u);
    zsp = REG32(0x500a0024u);
    phy = REG32(0x500a0028u);
    publish_power_snapshot(119u, 0x27000000u, value, zsp, phy);
    return phy == 3u ? 1u : 0x421u;
}

/* Read the active receive bandwidth from the software context validated by
   the host preflight. Native PHY/RF init may rewrite these volatile fields,
   so capture the value before entering that chain. */
static uint32_t ready_rx_bandwidth(void) {
    volatile const uint32_t *rf =
        (volatile const uint32_t *)RXCAPT_RF_INFO_ADDRESS;
    volatile const uint16_t *rf16 =
        (volatile const uint16_t *)RXCAPT_RF_INFO_ADDRESS;
    volatile const uint32_t *rx =
        (volatile const uint32_t *)RXCAPT_RX_INFO_ADDRESS;
    volatile const uint16_t *rx16 =
        (volatile const uint16_t *)RXCAPT_RX_INFO_ADDRESS;
    uint32_t main_frequency = rf[0x1cu / 4u];
    /* RX_INFO begins 0x4c bytes into RF_INFO. These offsets are relative to
       that sub-structure, whereas the host parser's offsets are relative to
       RF_INFO_BASE. */
    uint32_t rx_frequency = rx[0x0cu / 4u];
    uint32_t bandwidth = rf16[0x24u / 2u];
    uint32_t rx_bandwidth = rx16[0x1cu / 2u];
    uint32_t agc = rx16[0x02u / 2u];
    if (!main_frequency) {
        progress(14u, RXCAPT_RF_INFO_ADDRESS + 0x1cu, main_frequency);
        return 0xffffffffu;
    }
    if (main_frequency != rx_frequency) {
        progress(14u, RXCAPT_RX_INFO_ADDRESS + 0x0cu, rx_frequency);
        return 0xffffffffu;
    }
    if (bandwidth >= 6u) {
        progress(14u, RXCAPT_RF_INFO_ADDRESS + 0x24u, bandwidth);
        return 0xffffffffu;
    }
    if (bandwidth != rx_bandwidth) {
        progress(14u, RXCAPT_RX_INFO_ADDRESS + 0x1cu, rx_bandwidth);
        return 0xffffffffu;
    }
    if (!agc) {
        progress(14u, RXCAPT_RX_INFO_ADDRESS + 0x02u, agc);
        return 0xffffffffu;
    }
    return bandwidth;
}

static void save_rx_profile_registers(volatile rxcapt_finite_state_t *s) {
    s->saved_txrx_sys_cfg = TXRX_REGS[0x10u / 4u];
    s->saved_txrx_stop_cfg = TXRX_REGS[0x14u / 4u];
    s->saved_txrx_rx_cfg = TXRX_REGS[0x20u / 4u];
    s->saved_txrx_rx_pre_cfg = TXRX_REGS[0x38u / 4u];
}

static void configure_rx_profile(volatile rxcapt_finite_state_t *s,
                                 uint32_t bandwidth) {
#if defined(RXCAPT_EXPERIMENTAL_PRE_SWITCH) && RXCAPT_EXPERIMENTAL_PRE_SWITCH
    uint32_t pre_cfg = rxcapt_rx_pre_switch_profile(bandwidth,CFG[10]);
#else
    uint32_t pre_cfg = rxcapt_rx_pre_profile(bandwidth);
#endif
    progress(34u, 0x25000038u, bandwidth);
    TXRX_REGS[0x38u / 4u] = pre_cfg;
    progress(35u, 0x25000010u, 1u);
    TXRX_REGS[0x10u / 4u] = 1u;
    progress(36u, 0x25000020u, 0x83u);
    TXRX_REGS[0x20u / 4u] = 0x83u;
    progress(37u, 0x25000014u, 0u);
    TXRX_REGS[0x14u / 4u] = 0u;
    __asm__ volatile("dsb sy" ::: "memory");
    s->configured_rx_pre_cfg = TXRX_REGS[0x38u / 4u];
    s->configured_rx_sys_cfg = TXRX_REGS[0x10u / 4u];
    s->configured_rx_cfg = TXRX_REGS[0x20u / 4u];
    s->configured_rx_stop_cfg = TXRX_REGS[0x14u / 4u];
    s->rx_bandwidth_index = bandwidth;
}

static void observe_rx_status(volatile rxcapt_finite_state_t *s) {
    s->observed_rx_ofdm_stat = TXRX_REGS[0xc0u / 4u];
    s->observed_rx_err_stat = TXRX_REGS[0xc8u / 4u];
    s->observed_rx_out_cfg = TXRX_REGS[0x50u / 4u];
    s->observed_st_cnt_framc = TXRX_REGS[0xd0u / 4u];
}

static void restore_rx_profile(volatile rxcapt_finite_state_t *s) {
    TXRX_REGS[0x10u / 4u] = s->saved_txrx_sys_cfg;
    TXRX_REGS[0x14u / 4u] = s->saved_txrx_stop_cfg;
    TXRX_REGS[0x20u / 4u] = s->saved_txrx_rx_cfg;
    TXRX_REGS[0x38u / 4u] = s->saved_txrx_rx_pre_cfg;
    __asm__ volatile("dsb sy" ::: "memory");
    s->restored_txrx_sys_cfg = TXRX_REGS[0x10u / 4u];
    s->restored_txrx_stop_cfg = TXRX_REGS[0x14u / 4u];
    s->restored_txrx_rx_cfg = TXRX_REGS[0x20u / 4u];
    s->restored_txrx_rx_pre_cfg = TXRX_REGS[0x38u / 4u];
}

static uint32_t irq_mask(void) {
    uint32_t value;
    __asm__ volatile("mrs %0,cpsr\ncpsid if" : "=r"(value) :: "memory");
    return value;
}

static void irq_restore(uint32_t value) {
    __asm__ volatile("dsb sy\nmsr cpsr_c,%0" :: "r"(value) : "memory");
}

static void copy_words(volatile uint32_t *dst, volatile const uint32_t *src,
                       uint32_t count) {
    for (uint32_t i = 0; i < count; ++i) dst[i] = src[i];
}

static int memory_layout_valid(void) {
    volatile const uint32_t *info =
        (volatile const uint32_t *)RXCAPT_MEMORY_INFO_ADDRESS;
    return info[0] == 0x80880000u && info[1] == 0x000e0000u &&
           info[2] == 0x59u && info[3] == 0x80960000u &&
           info[4] == 0x0000ff00u && info[5] == 0x8096ff00u &&
           info[6] == 8u;
}

static int capture_table_is_zero(void) {
    volatile const uint32_t *table =
        (volatile const uint32_t *)RXCAPT_CONFIG_TABLE_ADDRESS;
    for (uint32_t i = 0; i < 8u; ++i) if (table[i]) return 0;
    return 1;
}

static void save_software_state(volatile rxcapt_finite_state_t *s) {
    volatile const uint32_t *globals =
        (volatile const uint32_t *)RXCAPT_GLOBALS_ADDRESS;
    volatile const uint32_t *data =
        (volatile const uint32_t *)RXCAPT_DATA_DESCRIPTOR_ADDRESS;
    volatile const uint32_t *head =
        (volatile const uint32_t *)RXCAPT_HEAD_DESCRIPTOR_ADDRESS;
    volatile const uint32_t *table =
        (volatile const uint32_t *)RXCAPT_CONFIG_TABLE_ADDRESS;
    volatile const uint32_t *dmach =
        (volatile const uint32_t *)RXCAPT_DMACH_ADDRESS;
    volatile const uint32_t *info =
        (volatile const uint32_t *)RXCAPT_MEMORY_INFO_ADDRESS;
    volatile const uint32_t *callbacks =
        (volatile const uint32_t *)RXCAPT_CALLBACK_TABLE_ADDRESS;

    copy_words(s->saved_rxcap_globals, globals, 4u);
    s->saved_rxcap_dmach = dmach[0];
    s->saved_capture_bitmap =
        *(volatile const uint16_t *)RXCAPT_CAPTURE_BITMAP_ADDRESS;
    s->saved_dma_allocator_bitmap = REG32(RXCAPT_DMA_ALLOCATOR_ADDRESS);
    s->saved_rxcap_block_num = info[6];
    copy_words(s->saved_capture_table, table, 8u);
    copy_words(s->saved_data_descriptor, data, 11u);
    copy_words(s->saved_head_descriptor, head, 11u);
    copy_words(s->saved_dma_entries_7_9, callbacks + 14u, 6u);
}

static void release_allocated_channels(uint32_t first, uint32_t second) {
    if (first >= 7u && first <= 9u)
        ((rxcap_release_fn)RXCAPT_DMA_RELEASE_ENTRY)(first);
    if (second >= 7u && second <= 9u && second != first)
        ((rxcap_release_fn)RXCAPT_DMA_RELEASE_ENTRY)(second);
}

static uint32_t reject_prepare(volatile rxcapt_finite_state_t *s,
                               uint32_t error) {
    s->error = error;
    s->phase = RXCAPT_PHASE_REJECTED;
    __asm__ volatile("dmb sy" ::: "memory");
    return error;
}

static void restore_software_state(volatile rxcapt_finite_state_t *s) {
    volatile uint32_t *globals = (volatile uint32_t *)RXCAPT_GLOBALS_ADDRESS;
    volatile uint32_t *data =
        (volatile uint32_t *)RXCAPT_DATA_DESCRIPTOR_ADDRESS;
    volatile uint32_t *head =
        (volatile uint32_t *)RXCAPT_HEAD_DESCRIPTOR_ADDRESS;
    volatile uint32_t *table =
        (volatile uint32_t *)RXCAPT_CONFIG_TABLE_ADDRESS;
    volatile uint32_t *dmach = (volatile uint32_t *)RXCAPT_DMACH_ADDRESS;

    copy_words(globals, s->saved_rxcap_globals, 4u);
    dmach[0] = s->saved_rxcap_dmach;
    *(volatile uint16_t *)RXCAPT_CAPTURE_BITMAP_ADDRESS =
        (uint16_t)s->saved_capture_bitmap;
    copy_words(table, s->saved_capture_table, 8u);
    copy_words(data, s->saved_data_descriptor, 11u);
    copy_words(head, s->saved_head_descriptor, 11u);
}

static uint32_t dma_channel_base(uint32_t channel) {
    volatile const uint32_t *table =
        (volatile const uint32_t *)RXCAPT_DMA_CHANNEL_TABLE_ADDRESS;
    if (channel >= DMA_CHANNEL_COUNT) return 0;
    uint32_t base = table[channel];
    if ((base & 3u) || base < 0x22000000u || base >= 0x22100000u) return 0;
    return base;
}

static int dma_channel_idle(uint32_t channel) {
    uint32_t address = dma_channel_base(channel);
    if (!address) return 0;
    volatile uint32_t *dma = (volatile uint32_t *)address;
    uint32_t status = dma[6];
    if ((dma[0] & 1u) || (status & DMA_RUN_MASK) ||
        (status & DMA_INTERRUPT_STATUS_MASK) ||
        (status & DMA_RESPONSE_ERROR_MASK)) return 0;
    if (status & DMA_COUNT_FINISH_STATUS) {
        dma[6] = DMA_COUNT_FINISH_STATUS;
        __asm__ volatile("dsb sy" ::: "memory");
        if (dma[6] & DMA_COUNT_FINISH_STATUS) return 0;
    }
    return 1;
}

static int stop_dma_channel(uint32_t channel, volatile uint32_t *poll_count) {
    uint32_t address = dma_channel_base(channel);
    if (!address) return 0;
    volatile uint32_t *dma = (volatile uint32_t *)address;
    dma[0] &= ~1u;
    __asm__ volatile("dsb sy" ::: "memory");
    for (uint32_t i = 0; i < 250000u; ++i) {
        if (!(dma[6] & DMA_RUN_MASK)) {
            *poll_count = i + 1u;
            return 1;
        }
    }
    *poll_count = 250000u;
    return 0;
}

static int restore_after_stop(volatile rxcapt_finite_state_t *s,
                              uint32_t success) {
    uint32_t data = s->data_channel;
    uint32_t head = s->head_channel;
    uint32_t irq_state = irq_mask();
    uint32_t channel_mask = (1u << data) | (1u << head);

    progress(80u, 0x27000004u, success);
    RXCAPT_REGS[1] &= ~1u;
    RXCAPT_REGS[4] &= ~3u;
    __asm__ volatile("dsb sy" ::: "memory");

    int data_stopped = stop_dma_channel(data, &s->data_stop_polls);
    int head_stopped = stop_dma_channel(head, &s->head_stop_polls);
    if (!data_stopped || !head_stopped) {
        s->error = !data_stopped ? 0x301u : 0x302u;
        s->phase = RXCAPT_PHASE_PINNED;
        __asm__ volatile("dmb sy" ::: "memory");
        irq_restore(irq_state);
        return 0;
    }

    volatile uint32_t *data_dma = (volatile uint32_t *)dma_channel_base(data);
    volatile uint32_t *head_dma = (volatile uint32_t *)dma_channel_base(head);
    observe_rx_status(s);
    uint32_t data_status = data_dma[6];
    uint32_t head_status = head_dma[6];
    uint32_t data_remaining = data_dma[4];
    uint32_t head_remaining = head_dma[4];
    s->data_dma_status = data_status;
    s->head_dma_status = head_status;
    s->data_observed_bytes =
        s->data_callback_count * RXCAPT_DATA_WINDOW_BYTES;
    s->head_observed_bytes =
        s->head_callback_count * RXCAPT_HEAD_WINDOW_BYTES;
    if (!(s->done_mask & 1u) &&
        data_remaining <= RXCAPT_DATA_WINDOW_BYTES)
        s->data_observed_bytes +=
            RXCAPT_DATA_WINDOW_BYTES - data_remaining;
    if (!(s->done_mask & 2u) &&
        head_remaining <= RXCAPT_HEAD_WINDOW_BYTES)
        s->head_observed_bytes +=
            RXCAPT_HEAD_WINDOW_BYTES - head_remaining;

    /* Response errors are not acknowledged here: their W1C semantics have
       not been verified on this target, so retain channel ownership and the
       resident callback instead of returning a possibly poisoned channel. */
    if ((data_status & DMA_RESPONSE_ERROR_MASK) ||
        (head_status & DMA_RESPONSE_ERROR_MASK)) {
        s->error = 0x306u;
        s->data_valid_bytes = 0u;
        s->head_valid_bytes = 0u;
        s->phase = RXCAPT_PHASE_PINNED;
        __asm__ volatile("dmb sy" ::: "memory");
        irq_restore(irq_state);
        return 0;
    }

    if (success && ((data_status & DMA_COUNT_FINISH_STATUS) == 0u ||
                    (head_status & DMA_COUNT_FINISH_STATUS) == 0u ||
                    data_remaining != 0u || head_remaining != 0u)) {
        s->error = 0x305u;
        success = 0u;
        s->data_valid_bytes = 0u;
        s->head_valid_bytes = 0u;
    }

    /* The HAL ISR acknowledges global channel bits before local STATUS bits. */
    uint32_t pending = DMA_IRQ_MASK & channel_mask;
    if (pending) DMA_IRQ_MASK = pending;
    __asm__ volatile("dsb sy" ::: "memory");
    data_status = data_dma[6];
    head_status = head_dma[6];
    data_dma[6] = data_status &
                  (DMA_INTERRUPT_STATUS_MASK | DMA_COUNT_FINISH_STATUS);
    head_dma[6] = head_status &
                  (DMA_INTERRUPT_STATUS_MASK | DMA_COUNT_FINISH_STATUS);
    __asm__ volatile("dsb sy" ::: "memory");
    data_status = data_dma[6];
    head_status = head_dma[6];
    if ((data_status & DMA_RESPONSE_ERROR_MASK) ||
        (head_status & DMA_RESPONSE_ERROR_MASK)) {
        s->error = 0x306u;
        s->data_valid_bytes = 0u;
        s->head_valid_bytes = 0u;
        s->phase = RXCAPT_PHASE_PINNED;
        __asm__ volatile("dmb sy" ::: "memory");
        irq_restore(irq_state);
        return 0;
    }
    if ((DMA_IRQ_MASK & channel_mask) ||
        (data_dma[6] & (DMA_INTERRUPT_STATUS_MASK | DMA_COUNT_FINISH_STATUS)) ||
        (head_dma[6] & (DMA_INTERRUPT_STATUS_MASK | DMA_COUNT_FINISH_STATUS))) {
        s->error = 0x303u;
        s->phase = RXCAPT_PHASE_PINNED;
        __asm__ volatile("dmb sy" ::: "memory");
        irq_restore(irq_state);
        return 0;
    }

    data_dma[1] = 0xffffu;
    head_dma[1] = 0xffffu;
    __asm__ volatile("dsb sy" ::: "memory");
    ((rxcap_card_fn)RXCAPT_DMA_COUNT_CLEAR_ENTRY)(data);
    ((rxcap_card_fn)RXCAPT_DMA_COUNT_CLEAR_ENTRY)(head);
    ((rxcap_lps_fn)RXCAPT_LPS_DMA_ENTRY)(data, 0u);
    ((rxcap_lps_fn)RXCAPT_LPS_DMA_ENTRY)(head, 0u);

    if (((*DMA_CONSTRAINT16 ^ (uint16_t)s->saved_dma_allocator_bitmap) &
         channel_mask) != 0u) {
        s->error = 0x307u;
        s->phase = RXCAPT_PHASE_PINNED;
        __asm__ volatile("dmb sy" ::: "memory");
        irq_restore(irq_state);
        return 0;
    }

    volatile uint32_t *callbacks =
        (volatile uint32_t *)RXCAPT_CALLBACK_TABLE_ADDRESS;
    uint32_t data_entry = 2u * (data - 7u);
    uint32_t head_entry = 2u * (head - 7u);
    callbacks[2u * data + 0u] = s->saved_dma_entries_7_9[data_entry];
    callbacks[2u * data + 1u] = s->saved_dma_entries_7_9[data_entry + 1u];
    callbacks[2u * head + 0u] = s->saved_dma_entries_7_9[head_entry];
    callbacks[2u * head + 1u] = s->saved_dma_entries_7_9[head_entry + 1u];
    ((rxcap_release_fn)RXCAPT_DMA_RELEASE_ENTRY)(data);
    ((rxcap_release_fn)RXCAPT_DMA_RELEASE_ENTRY)(head);

    if ((*DMA_ALLOC16 & channel_mask) != 0u) {
        s->error = 0x304u;
        s->phase = RXCAPT_PHASE_PINNED;
        __asm__ volatile("dmb sy" ::: "memory");
        irq_restore(irq_state);
        return 0;
    }

    restore_software_state(s);
    RXCAPT_REGS[1] = (RXCAPT_REGS[1] & ~1u) | (s->saved_capt_cfg & 1u);
    RXCAPT_REGS[4] = (RXCAPT_REGS[4] & ~3u) | (s->saved_dma_req_en & 3u);
    RXCAPT_REGS[0] = s->saved_rxcap_en;
    RXCAPT_REGS[9] = s->saved_capt_end_address;
    __asm__ volatile("dsb sy" ::: "memory");
    s->restored_rxcap_en = RXCAPT_REGS[0];
    s->restored_capt_cfg = RXCAPT_REGS[1];
    s->restored_dma_req_en = RXCAPT_REGS[4];
    s->restored_capt_end_address = RXCAPT_REGS[9];
    restore_rx_profile(s);
    s->restored_dma_allocator_bitmap = REG32(RXCAPT_DMA_ALLOCATOR_ADDRESS);
    s->restored_data_callback = callbacks[2u * data + 1u];
    s->restored_head_callback = callbacks[2u * head + 1u];
    s->restored_dma_irq_status = DMA_IRQ_MASK & channel_mask;
    s->restored_data_conf = data_dma[0];
    s->restored_head_conf = head_dma[0];
    s->restored_data_status = data_dma[6];
    s->restored_head_status = head_dma[6];
    s->restored_data_map = data_dma[1];
    s->restored_head_map = head_dma[1];
    s->restored_data_count = data_dma[4];
    s->restored_head_count = head_dma[4];
    __asm__ volatile("dmb sy" ::: "memory");
    irq_restore(irq_state);

    if (!success) {
        s->data_valid_bytes = 0u;
        s->head_valid_bytes = 0u;
    }
    s->phase = success ? RXCAPT_PHASE_HELD : RXCAPT_PHASE_ABORTED;
    __asm__ volatile("dmb sy" ::: "memory");
    return 1;
}

static uint32_t prepare(void) {
    volatile rxcapt_finite_state_t *s = STATE;
    volatile const uint32_t *globals =
        (volatile const uint32_t *)RXCAPT_GLOBALS_ADDRESS;
    if (s->magic || s->phase) return 0x401u;
    if (!memory_layout_valid()) return 0x402u;
    if (!capture_table_is_zero()) return 0x403u;
    if (*(volatile const uint16_t *)RXCAPT_CAPTURE_BITMAP_ADDRESS) return 0x404u;
    if (((*DMA_ALLOC16 | *DMA_CONSTRAINT16) & 0x0380u) != 0u) return 0x405u;
    /* The RF profile depends on the configured receive bandwidth. Snapshot it
       before native init: L1/RF initialization may clear or repurpose the
       software context fields even though their pre-init values are valid. */
    /* terminal_dispatch validates this snapshot before force_idle(). */
    uint32_t rx_bandwidth = M[23];
    if (rx_bandwidth >= 6u) return 0x415u;
    if (rx_bandwidth == 0xffffffffu) return 0x415u;

    /* Idle firmware may gate both domains between host commands. Keep the
       already hardware-verified power and isolated RF-init chain in this
       same PREPARE transaction, immediately before RXCAPT/DMA setup. */
    uint32_t rf_init_result = isolated_phy_hw_init_and_probe();
    if (rf_init_result != 1u) return rf_init_result;
    if (!domains_ready()) return 0x414u;
    progress(10u, 0x27000000u, 0u);
    if (RXCAPT_REGS[0] || (RXCAPT_REGS[1] & 1u) || (RXCAPT_REGS[4] & 3u)) return 0x406u;
    progress(11u, 0x2200000cu, 0u);
    if (DMA_IRQ_MASK & 0x0380u) return 0x409u;
    for (uint32_t i = 0; i < 4u; ++i) if (globals[i]) return 0x40du;
    for (uint32_t channel = 7u; channel <= 9u; ++channel) {
        progress(12u, 0x22000040u + channel * 64u, channel);
        if (!dma_channel_idle(channel)) return 0x40cu;
    }

    uint32_t irq_state = irq_mask();
    volatile uint32_t *state_words = (volatile uint32_t *)s;
    for (uint32_t i = 0; i < sizeof(*s) / sizeof(uint32_t); ++i)
        state_words[i] = 0u;

    s->magic = RXCAPT_FINITE_MAGIC;
    s->version = 1u;
    s->phase = RXCAPT_PHASE_PREPARING;
    s->error = 0;
    s->done_mask = 0;
    s->data_valid_bytes = 0;
    s->head_valid_bytes = 0;
    s->data_event_mask = 0;
    s->head_event_mask = 0;
    s->data_callback_count = 0;
    s->head_callback_count = 0;
    s->data_observed_bytes = 0;
    s->head_observed_bytes = 0;
    s->data_stop_polls = 0;
    s->head_stop_polls = 0;
    s->saved_rxcap_en = RXCAPT_REGS[0];
    s->saved_capt_cfg = RXCAPT_REGS[1];
    s->saved_dma_req_en = RXCAPT_REGS[4];
    s->saved_capt_end_address = RXCAPT_REGS[9];
    save_software_state(s);
    s->rx_bandwidth_index = rx_bandwidth;
    save_rx_profile_registers(s);

    /* The vendor clear helper can wait forever in its STATUS.RUN loop. Its
       channel-7/8/9 request fields are recorded and checked under IRQ mask;
       this finite opener reconstruction does not call that helper at all. */
    progress(20u, RXCAPT_DMA_REQ_SEL_WORD_7_8, 0u);
    s->preflight_dma_req_sel_22000018 = DMA_REQ_SEL_7_8;
    s->preflight_dma_req_sel_2200001c = DMA_REQ_SEL_8_9;
    if ((s->preflight_dma_req_sel_22000018 & 0x70000000u) ||
        (s->preflight_dma_req_sel_2200001c & 0x00000077u)) {
        uint32_t result = reject_prepare(s, 0x40eu);
        irq_restore(irq_state);
        return result;
    }

    uint16_t allocated_before = *DMA_ALLOC16;
    uint16_t constrained_before = *DMA_CONSTRAINT16;
    if (((allocated_before | constrained_before) & 0x0380u) != 0u) {
        uint32_t result = reject_prepare(s, 0x411u);
        irq_restore(irq_state);
        return result;
    }

    progress(30u, RXCAPT_DMA_ALLOC_ENTRY, 1u);
    uint32_t data_channel =
        ((rxcap_alloc_fn)RXCAPT_DMA_ALLOC_ENTRY)(1u);
    if (data_channel < 7u || data_channel > 9u) {
        uint32_t result = reject_prepare(s, 0x411u);
        irq_restore(irq_state);
        return result;
    }
    s->data_channel = data_channel;
    progress(31u, RXCAPT_DMA_ALLOC_ENTRY, 1u);
    uint32_t head_channel =
        ((rxcap_alloc_fn)RXCAPT_DMA_ALLOC_ENTRY)(1u);
    if (head_channel < 7u || head_channel > 9u ||
        head_channel == data_channel) {
        release_allocated_channels(data_channel, head_channel);
        uint32_t result = reject_prepare(s, 0x412u);
        irq_restore(irq_state);
        return result;
    }

    s->head_channel = head_channel;
    progress(32u, 0u, 0u);
    uint16_t expected_allocations =
        (uint16_t)((1u << data_channel) | (1u << head_channel));
    uint16_t allocated_now = *DMA_ALLOC16;
    if ((allocated_now & expected_allocations) != expected_allocations ||
        ((allocated_now ^ allocated_before) & 0x0380u) !=
            expected_allocations ||
        ((*DMA_CONSTRAINT16 ^ constrained_before) & 0x0380u) != 0u) {
        release_allocated_channels(data_channel, head_channel);
        uint32_t result = reject_prepare(s, 0x413u);
        irq_restore(irq_state);
        return result;
    }

    volatile uint8_t *channels = (volatile uint8_t *)RXCAPT_DMACH_ADDRESS;
    channels[0] = (uint8_t)data_channel;
    channels[1] = (uint8_t)head_channel;
    s->data_channel = data_channel;
    s->head_channel = head_channel;
    s->data_vendor_callback = RXCAPT_VENDOR_DATA_CALLBACK;
    s->head_vendor_callback = RXCAPT_VENDOR_HEAD_CALLBACK;
    uint32_t data_restore_index = 2u * (data_channel - 7u);
    uint32_t head_restore_index = 2u * (head_channel - 7u);
    s->data_restore_callback =
        s->saved_dma_entries_7_9[data_restore_index + 1u];
    s->head_restore_callback =
        s->saved_dma_entries_7_9[head_restore_index + 1u];

    /* Rebuild the vendor's short setup chain without calling its synchronous
       opener: SD buffers, two finite descriptors, callback handoff, then DMA
       start and LPS constraints. The original block count stays untouched. */
    progress(33u, RXCAPT_SD_INFO_ENTRY, 0u);
    ((void (*)(void))RXCAPT_SD_INFO_ENTRY)();
    volatile uint32_t *rxcap_globals =
        (volatile uint32_t *)RXCAPT_GLOBALS_ADDRESS;
    rxcap_globals[1] = RXCAPT_DATA_WINDOW_BYTES;
    rxcap_globals[3] = RXCAPT_HEAD_WINDOW_BYTES;

    volatile uint32_t *data =
        (volatile uint32_t *)RXCAPT_DATA_DESCRIPTOR_ADDRESS;
    volatile uint32_t *head =
        (volatile uint32_t *)RXCAPT_HEAD_DESCRIPTOR_ADDRESS;
    data[0] = 0x521du;
    data[1] = 0x0c0cu;
    data[2] = 0x27010000u;
    data[3] = rxcap_globals[0];
    data[4] = RXCAPT_DATA_WINDOW_BYTES;
    data[5] = RXCAPT_DATA_WINDOW_BYTES;
    head[0] = 0x521du;
    head[1] = 0x0d0du;
    head[2] = 0x27010000u +
              (RXCAPT_FINITE_CAPTURE_END_ADDRESS + 1u) * 4u;
    head[3] = rxcap_globals[2];
    head[4] = RXCAPT_HEAD_WINDOW_BYTES;
    head[5] = RXCAPT_HEAD_WINDOW_BYTES;

    volatile uint32_t *callbacks =
        (volatile uint32_t *)RXCAPT_CALLBACK_TABLE_ADDRESS;
    callbacks[2u * data_channel + 1u] = RXCAPT_FINITE_DATA_CALLBACK;
    callbacks[2u * head_channel + 1u] = RXCAPT_FINITE_HEAD_CALLBACK;
    s->data_valid_bytes = 0u;
    s->head_valid_bytes = 0u;
    __asm__ volatile("dsb sy\ndmb sy" ::: "memory");
    s->phase = RXCAPT_PHASE_PREPARED;
    __asm__ volatile("dmb sy" ::: "memory");

    /* RXCAPT receives the LTE RX datapath. Start the validated direct RX
       trace profile before the finite channels and capture requests are armed;
       this profile does not launch synchronization, FFT, or decoding. */
    configure_rx_profile(s, rx_bandwidth);

    progress(40u, RXCAPT_DMA_START_ENTRY, data_channel);
    ((rxcap_dma_start_fn)RXCAPT_DMA_START_ENTRY)(
        2u, data_channel, (const uint32_t *)RXCAPT_DATA_DESCRIPTOR_ADDRESS);
    progress(41u, RXCAPT_DMA_START_ENTRY, head_channel);
    ((rxcap_dma_start_fn)RXCAPT_DMA_START_ENTRY)(
        2u, head_channel, (const uint32_t *)RXCAPT_HEAD_DESCRIPTOR_ADDRESS);
    progress(50u, RXCAPT_LPS_DMA_ENTRY, data_channel);
    ((rxcap_lps_fn)RXCAPT_LPS_DMA_ENTRY)(data_channel, 1u);
    progress(51u, RXCAPT_LPS_DMA_ENTRY, head_channel);
    ((rxcap_lps_fn)RXCAPT_LPS_DMA_ENTRY)(head_channel, 1u);
    progress(60u, 0u, 0u);
    irq_restore(irq_state);
    return s->phase;
}

static uint32_t arm(void) {
    volatile rxcapt_finite_state_t *s = STATE;
    if (s->magic != RXCAPT_FINITE_MAGIC || s->phase != RXCAPT_PHASE_PREPARED)
        return 0x501u;

    progress(70u, RXCAPT_CAL_CAPTURE_ENTRY, 0u);
    ((rxcap_card_fn)RXCAPT_CAL_CAPTURE_ENTRY)(0u);
    volatile uint32_t *table =
        (volatile uint32_t *)RXCAPT_CONFIG_TABLE_ADDRESS;
    if (table[0] != 3u || table[2] != 1u ||
        table[3] != 1999u) {
        s->error = 0x502u;
        s->phase = RXCAPT_PHASE_FAILED;
        return 0x502u;
    }

#if RXCAPT_FINITE_CAPTURE_END_ADDRESS != 1999u
    /* The verified vendor producer initializes the one capture window to
       1999. Change only that field after validating the vendor result. */
    table[3] = RXCAPT_FINITE_CAPTURE_END_ADDRESS;
    __asm__ volatile("dmb sy" ::: "memory");
#endif
    s->candidate_end_address = table[3];
    s->done_mask = 0;
    s->error = 0;
    s->phase = RXCAPT_PHASE_RUNNING;
    __asm__ volatile("dmb sy" ::: "memory");
    progress(71u, RXCAPT_UPDATE_CAPTURE_ENTRY, 0u);
    ((rxcap_card_fn)RXCAPT_UPDATE_CAPTURE_ENTRY)(0u);
    progress(72u, 0u, 0u);
    __asm__ volatile("dmb sy" ::: "memory");
    return s->phase;
}

/* Keep RF init, finite DMA setup, and RXCAPT arm in one mailbox call so the
   host cannot leave the freshly opened domains idle between those stages. */
static uint32_t init_and_arm(void) {
    uint32_t prepared = prepare();
    if (prepared != RXCAPT_PHASE_PREPARED) return prepared;
    return arm();
}

static uint32_t snapshot(void) {
    volatile const uint32_t *src = (volatile const uint32_t *)STATE;
    volatile uint32_t *dst =
        (volatile uint32_t *)RXCAPT_FINITE_SNAPSHOT_ADDRESS;
    uint32_t state_words = sizeof(rxcapt_finite_state_t) / sizeof(uint32_t);
    uint32_t irq_state = irq_mask();
    uint32_t phase = STATE->phase;
    if (phase == RXCAPT_PHASE_RUNNING || phase == RXCAPT_PHASE_COMPLETE ||
        phase == RXCAPT_PHASE_FAILED || phase == RXCAPT_PHASE_PINNED)
        observe_rx_status(STATE);
    for (uint32_t i = 0; i < RXCAPT_FINITE_SNAPSHOT_WORDS; ++i)
        dst[i] = i < state_words ? src[i] : 0u;
    for (uint32_t i = 110u; i < 124u; ++i) dst[i] = 0u;
    if ((phase == RXCAPT_PHASE_RUNNING || phase == RXCAPT_PHASE_FAILED ||
         phase == RXCAPT_PHASE_PINNED) &&
        STATE->data_channel >= 7u && STATE->data_channel <= 9u &&
        STATE->head_channel >= 7u && STATE->head_channel <= 9u &&
        STATE->data_channel != STATE->head_channel) {
        uint32_t data_base = dma_channel_base(STATE->data_channel);
        uint32_t head_base = dma_channel_base(STATE->head_channel);
        if (data_base && head_base) {
            volatile const uint32_t *data_dma =
                (volatile const uint32_t *)data_base;
            volatile const uint32_t *head_dma =
                (volatile const uint32_t *)head_base;
            volatile const uint32_t *callbacks =
                (volatile const uint32_t *)RXCAPT_CALLBACK_TABLE_ADDRESS;
            dst[110] = 0x444d4131u; /* DMA1: live DMA snapshot follows */
            dst[111] = DMA_IRQ_MASK;
            dst[112] = data_base;
            dst[113] = data_dma[0];
            dst[114] = data_dma[2];
            dst[115] = data_dma[4];
            dst[116] = data_dma[6];
            dst[117] = head_base;
            dst[118] = head_dma[0];
            dst[119] = head_dma[2];
            dst[120] = head_dma[4];
            dst[121] = head_dma[6];
            dst[122] = callbacks[2u * STATE->data_channel + 1u];
            dst[123] = callbacks[2u * STATE->head_channel + 1u];
        }
    }
    __asm__ volatile("dmb sy" ::: "memory");
    irq_restore(irq_state);
    return phase;
}

/* Generic monitor writes exclude this vendor destination. Restore only its
   fixed 64 KiB lease, in <=1024-byte chunks staged in debug scratch. A caller
   must have detached hardware first; running/pinned states are rejected. */
static uint32_t restore_chunk(uint32_t index) {
    volatile rxcapt_finite_state_t *s = STATE;
    if (index >= 64u) return 0x701u;
    if (s->phase != RXCAPT_PHASE_EMPTY && s->phase != RXCAPT_PHASE_HELD &&
        s->phase != RXCAPT_PHASE_ABORTED && s->phase != RXCAPT_PHASE_REJECTED)
        return 0x702u;
    uint32_t address = 0x80960000u + index * 1024u;
    uint32_t bytes = index == 63u ? 960u : 1024u;
    copy_words((volatile uint32_t *)address,
               (volatile const uint32_t *)0x8097e000u, bytes / 4u);
    for (uint32_t line = address; line < address + bytes; line += 32u)
        __asm__ volatile("mcr p15,0,%0,c7,c10,1" :: "r"(line) : "memory");
    __asm__ volatile("dsb sy" ::: "memory");
    return 0x3000u + index;
}


