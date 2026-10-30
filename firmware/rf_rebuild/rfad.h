#ifndef UIS8910_RFAD_H
#define UIS8910_RFAD_H

#include "rf_bus.h"

#define RFAD_BASE UINT32_C(0x25100000)
#define RFAD_EVENT_VALID UINT32_C(0x40000000)
#define RFAD_EVENT_END UINT32_C(0x80000000)

struct rfad_power_context {
    uint32_t sleep_lock;
    void *irq_context;
    uint32_t (*save_disable_irq)(void *context);
    void (*restore_irq)(void *context, uint32_t saved);
};

/* Low-level vendor behavior: polling is unbounded and status words must
 * change externally. LTE PHY requests update 0x500a000c; the 0x2000 sleep
 * constraint changes under saved/restored IRQ masking only after success.
 * ZSP open writes its poll byte to +0x54 and waits for +0x24==3; close only
 * writes +0x50 and neither waits nor drops the LTE PHY constraint.
 * The idle-word initializer writes 0x500900c4/f0, not domain status.
 * All callers need exclusive ownership; no RF/DMA task takeover is provided. */
void rfad_initialize_idle_words(const struct rf_bus *bus);
void rfad_zsp_open(const struct rf_bus *bus, uint8_t poll);
void rfad_zsp_close(const struct rf_bus *bus, uint8_t poll);
void rfad_lte_phy_open(const struct rf_bus *bus, const struct rfad_power_context *context);
void rfad_lte_phy_close(const struct rf_bus *bus, const struct rfad_power_context *context);
void rfad_erc_domains_open(const struct rf_bus *bus, const struct rfad_power_context *context);

enum rfad_power_result {
    RFAD_POWER_OK = 0,
    RFAD_POWER_INVALID_BUDGET = -1,
    RFAD_POWER_PHY_AVAILABLE_TIMEOUT = -2,
    RFAD_POWER_PHY_STATE_TIMEOUT = -3,
    RFAD_POWER_ZSP_TIMEOUT = -4
};

/* New bounded entry, not a vendor function. budget limits the total number
 * of status samples (not time) across both domains. Zero returns before any
 * bus/IRQ activity. Nonzero emits the ERC setup then preserves vendor access
 * order while budget remains. On timeout, requests already issued and a
 * successfully acquired PHY constraint remain in place: caller retains
 * ownership and must reconcile hardware before retry/release. Never accesses
 * RFAD, DMA or reset registers; success is not an IQ-ready guarantee. */
int rfad_erc_domains_open_checked(const struct rf_bus *bus,
                                  const struct rfad_power_context *context,
                                  uint32_t budget);

struct rfad_afc_context {
    uint32_t card_index;
    uint32_t frequency_offset;
    uint32_t thermal_compensation;
};

/* Current card index must select readable words (the vendor has two cards).
 * Both inputs and the saturated result retain vendor raw units. Addition
 * wraps to 32 bits before signed saturation to +/-32766. No AFC estimator,
 * thermal calibration or oscillator feedback loop is supplied. */
void rfad_afc_commands(const struct rf_bus *bus, const struct rfad_afc_context *context,
                       uint32_t slots);
void rfad_afc_nodci_commands(const struct rf_bus *bus, const struct rfad_afc_context *context,
                             uint32_t slots);

/* Copy the 16 NV parameter spans in vendor order using halfword accesses,
 * preserving holes, then clear three 20-byte GSM timing arrays if their
 * format word differs from 0x5555aaaa. nv/rfnv need 22528/16384 bytes.
 * This does not initialize RFAD event tables or apply board calibration. */
void rfad_load_nv_parameters(const struct rf_bus *bus, uint32_t nv, uint32_t rfnv);

/* Isolated, closed table-update region of rf_lte_init_hw, not the whole
 * initializer. tables is noffsdl; the seven arrays span tables-0x36..+0x144.
 * Stops at the first band 41 even for an unknown additive_flag; preceding
 * band-28 updates persist. Does not restore default rows on later calls. */
void rfad_apply_nv_channel_tables(const struct rf_bus *bus, uint32_t rfnv, uint32_t tables);

/* Raw hal_LpsSetRfSystemClock behavior at 0x50035000. Preserves the 122.88M
 * three-store sequence and read-dependent second store for other inputs.
 * Other inputs select the original fallback encoding. This is neither an
 * ADC sample-rate API nor a complete PLL/power/sleep-wake configuration. */
void rfad_set_system_clock(const struct rf_bus *bus, uint32_t clock);

/* rf_lte_channel_to_freq: 27 mutable halfword entries per table. tables points
 * to noffsdl; nmaxdl is +0x36, fdllow +0xa2 and fuplow +0xd8.
 * Returns vendor raw units, not Hz. direction=0 selects DL, all other int16
 * values select UL. Unmatched channels use row 0 in this behavioral replica.
 * The checked API accepts only direction 0/1 and a matching uint16 channel;
 * it writes one raw word to output on success and returns -1 without writes
 * on invalid input. Supply the current tables after vendor/NV initialization,
 * with exclusive ownership, and a disjoint aligned output address. */
uint32_t rfad_channel_frequency(const struct rf_bus *bus, uint32_t tables,
                                int16_t direction, uint16_t channel);
int rfad_channel_frequency_checked(const struct rf_bus *bus, uint32_t tables,
                                   unsigned direction, uint32_t channel,
                                   uint32_t output);

/* Version-specific runtime addresses supplied by the caller. No factory NV,
 * calibration curve or gain table is synthesized. The context itself must
 * remain stable and disjoint from all observed bus memory and destinations.
 * Table selectors are 0=LB, 1=MB, 2=HB; these names do not define RF ranges. */
struct rfad_rx_context {
    uint32_t info;
    uint32_t rx_info;
    uint32_t rfnv;
    uint32_t calib_tab_pointer;
    uint32_t rf_tab_pointer;
    uint32_t ct_ctrl;
    uint32_t lte_trace;
    uint32_t calib_gain;
    uint32_t new_agc[3];
    uint32_t agc[3];
};

/* Low-level replicas: caller owns RF state and supplies readable calibration
 * objects/tables and writable trace/command slots. Gain input is a vendor
 * index, not dB. Compensation can change the index after the initial 124 cap;
 * the caller must ensure the resulting table accesses are valid. No bounds
 * preflight, power/clock enable, RFAD submission or PLL wait is supplied. */
uint32_t rfad_agc_word(const struct rf_bus *bus, const struct rfad_rx_context *context,
                       uint32_t index, int16_t correction);
uint32_t rfad_agc_compensate(const struct rf_bus *bus, const struct rfad_rx_context *context,
                             uint32_t index);
void rfad_rxon_gain(const struct rf_bus *bus, const struct rfad_rx_context *context,
                    uint32_t slots, uint16_t index);
void rfad_rxon_parameters(const struct rf_bus *bus, const struct rfad_rx_context *context,
                          uint32_t slots);

/* Behavioral reconstructions for CP BIN bd25923a..., not a public Hz API.
 * slots points to rf_lte_ram2_rfad_addr_t; rx_info to rf_lterx_info_tag.
 * The frequency field at rx_info+12 remains in vendor raw units.
 * These functions generate command words. They do not prove execution/lock. */
void rfad_event_valid(const struct rf_bus *bus, uint32_t event);
void rfad_event_invalid(const struct rf_bus *bus, uint32_t event);
void rfad_event_invalid_end(const struct rf_bus *bus, uint32_t event);
void rfad_event_data_modify(const struct rf_bus *bus, uint32_t event, uint32_t data);
void rfad_rx_frequency(const struct rf_bus *bus, uint32_t slots, uint32_t rx_info);
void rfad_rxon_frequency(const struct rf_bus *bus, uint32_t slots, uint32_t rx_info);

/* Rebuilds b_rfad_init's register setup, not RF cold initialization.
 * Preserves the original two GPO writes. NV is read at original offsets.
 * Returns -1 without writes when the two power-domain words are not 3;
 * this deliberately replaces the vendor's assert path, which is not emulated.
 * It never enables power domains on the caller's behalf. */
int rfad_configure_controller(const struct rf_bus *bus, uint32_t rfnv);

/* Bind one NV action to its command pointer/index. Configuration sizes are
 * 120 bytes (RAM1) and 200 bytes (RAM2), confirmed by reference DWARF.
 * Action is bits 12..19 of the NV head. Unknown actions leave config intact.
 * These functions bind addresses; they do not copy/submit the NV commands. */
void rfad_bind_ram1(const struct rf_bus *bus, uint32_t config,
                   uint32_t nv_action, uint32_t command);
void rfad_bind_ram2(const struct rf_bus *bus, uint32_t config,
                   uint32_t nv_action, uint32_t command, uint16_t ram1_index);

/* b_rfad_mem12_init: load enabled NV event/action records into both banks.
 * nv is st_rf_lte_nv; down/up are rf_lte_ram_t runtime tables whose
 * ram1_ram2_ind/num fields must already have been prepared by the NV binder.
 * This does not initialize those tables, load RAM3, or wait for hardware. */
void rfad_load_templates(const struct rf_bus *bus, uint32_t nv,
                         uint32_t down, uint32_t up);

struct rfad_memory_context {
    uint32_t nv;
    uint32_t down;
    uint32_t up;
    void *irq_context;
    uint32_t (*save_disable_irq)(void *context);
    void (*restore_irq)(void *context, uint32_t saved);
};

/* b_rfad_mem_init: write control=0, alternately clear 384 words per bank,
 * load templates, then write control=3 with IRQ masked and restore it.
 * Callbacks must be non-failing. No safe takeover, power/clock management,
 * polling, or rollback is provided by this low-level behavioral replica. */
void rfad_initialize_memory(const struct rf_bus *bus,
                            const struct rfad_memory_context *context);

/* rf_lte_rfadnv_init reconstruction: initialize both runtime tables from NV.
 * Includes RAM1/2 indices/counts, event action lists and RAM3 pointer bindings;
 * it does not submit hardware commands. Behavioral equivalence is restricted
 * to structurally valid templates accepted by rfad_validate_runtime_nv.
 * The vendor has no bounds checks and can use an uninitialized group count.
 * New callers should use rfad_prepare_runtime, which validates before writes. */
void rfad_build_runtime(const struct rf_bus *bus, uint32_t nv, uint32_t down, uint32_t up);
int rfad_validate_runtime_nv(const struct rf_bus *bus, uint32_t nv);
int rfad_prepare_runtime(const struct rf_bus *bus, uint32_t nv, uint32_t down, uint32_t up);

#endif
