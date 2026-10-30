#ifndef UIS8910_RF_CORE_TUNE_FLOW_H
#define UIS8910_RF_CORE_TUNE_FLOW_H

#include "rf_core_tune_plan.h"

enum rf_core_flow_operation {
    RF_CORE_WRITE16 = 1,
    RF_CORE_WRITE32 = 2,
    RF_CORE_POLL16 = 3,
    RF_CORE_TIMER_WAIT = 4,
    RF_CORE_OR16 = 5 /* Read the live halfword, OR value, then write it back. */
};

struct rf_core_flow_step {
    uint32_t operation;
    uint32_t local_address;
    uint32_t value;
    uint32_t mask;
};

struct rf_core_flow_input {
    uint32_t requested_raw; /* Tail uses the uncorrected request, not working_raw. */
    struct rf_core_tune_input prefix;
    uint16_t table_slot; /* Validated 15-entry row index, 0..14. */
    uint16_t context_16;
    uint16_t word_8764;
    uint16_t word_9438;
    uint16_t pair_af78_first;
    uint16_t pair_af78_second;
    uint16_t control_32004_before;
};

struct rf_core_flow_bus {
    void *context;
    int (*read)(void *, uint32_t local_address, uint32_t bytes, uint32_t *value);
    int (*write)(void *, uint32_t local_address, uint32_t bytes, uint32_t value);
};

/* Original shared post-RX helper 0x38a8..0x3a7c. Called after RXON at
 * 0x616a and by retune at 0x66ce. Reads the live selector, four center words
 * and mode width table, rather than assuming their retained image defaults.
 * mode0..6 only; exclusive initialized RF context required. Preserves original
 * access order/widths, not processor timing. The original literal 0x50109050
 * is passed unchanged to the bus; no CP/AP address bridge is implied.
 * Returns0,-1 invalid contract (no IO),-2 bus failure; no rollback.
 * No ready/VCO read, no PLL-lock assertion; offline, not deployed. */
int rf_core_rxon_post_configure(const struct rf_core_flow_bus *,
                                uint32_t requested_raw, uint16_t mode);

struct rf_core_context_bus {
    void *context;
    int (*read16)(void *, uint32_t address, uint16_t *value);
};

struct rf_core_frequency_input {
    uint32_t requested_raw;
    uint16_t mode;
    uint16_t correction_index;
    uint16_t factor_state;
    uint16_t table_factor; /* Caller-resolved second-level BSS value. */
};

struct rf_core_frequency_output {
    uint32_t working_raw;
    uint32_t effective_raw;
    uint32_t fraction;
    int16_t correction;
    uint16_t denominator_factor;
    uint16_t q8;
    uint16_t mode_pair_first;
    uint16_t mode_pair_second;
    uint16_t reserved;
};

struct rf_core_tune_request {
    struct rf_core_frequency_input frequency;
    uint16_t selector;
    uint16_t control_before;
    uint16_t polling_enabled;
    uint16_t table_slot;
    uint16_t context_16;
    uint16_t word_8764;
    uint16_t word_9438;
    uint16_t pair_af78_first;
    uint16_t pair_af78_second;
    uint16_t control_32004_before;
};

/* Resolves fields consumed by the reconstructed retune path from the CP-visible
 * UIS8910 context. retune_argument is the entry's a0 value; its bit 13 is the
 * one-bit correction index extracted by p.extractu at RV 0x6390. The path is
 * only taken when bit 0 is set. requested_raw comes from the service request.
 * Reads only CP aliases already used by the live snapshot; no writes/MMIO
 * execution. Returns -1 for invalid context and -2 for a failed read, leaving
 * output unchanged. */
int rf_core_resolve_tune_request(const struct rf_core_context_bus *,
                                uint32_t requested_raw,
                                uint32_t retune_argument,
                                struct rf_core_tune_request *);

/* Reconstructs mode correction, the factor==1 table/default-7 selection,
 * and the two integer coefficients used by RV 0x37f0. Runtime factor-table
 * lookup is deliberately supplied by the caller; no address bridge implied.
 * Invalid modes/indexes/divisors return -1 without modifying output. */
int rf_core_calculate_tune_parameters(const struct rf_core_frequency_input *,
                                     struct rf_core_frequency_output *);
/* Combines C coefficient calculation with the existing pure write planner.
 * Runtime factor-table and calibration values are caller-resolved; no MMIO. */
int rf_core_build_tune_flow_request(const struct rf_core_tune_request *,
                                   struct rf_core_flow_step *, uint32_t capacity);

/* Analysis reconstruction of RV 0x6420 through its two tail calls at 0x66ce
 * and 0x66d4. Does not include input decoding/correction/frequency arithmetic,
 * function epilogue, optional hopping call, or cold initialization/calibration.
 * Table values must be resolved from one stable, initialized context at
 * slot=15*selector+table_slot: 8764+2*slot, 9438+2*slot, af78+4*slot.
 * Selectors 0..20 and modes 0..6 only. All addresses retain the RV local view;
 * this API neither proves nor installs a CP/AP address bridge. Input/output
 * must be disjoint. No output modification on invalid input/capacity (-1).
 * Maximum 33 steps. Planner performs no I/O. */
int rf_core_build_tune_flow(const struct rf_core_flow_input *,
                           struct rf_core_flow_step *, uint32_t capacity);

/* Callbacks require exclusive RF/timer ownership and a validated address
 * bridge. One post-stop CP-alias probe verified write-one-to-clear at
 * timer base+12; repeatability and integration remain untested. Count 122
 * is the original code's integer result of 122880000/1000000 for argument 1;
 * no physical timing accuracy is asserted. poll_budget bounds read attempts
 * per wait. Returns 0, -1 invalid arguments, -2 callback failure, -3 timeout.
 * Failure stops immediately; prior writes remain applied, with no rollback.
 * This executor is not wired into the receiver service. */
int rf_core_execute_tune_flow(const struct rf_core_flow_step *, uint32_t count,
                             const struct rf_core_flow_bus *, uint32_t poll_budget);

#endif
