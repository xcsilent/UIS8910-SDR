#ifndef RF_CORE_RXON_B_H
#define RF_CORE_RXON_B_H
#include "rf_core_rxon_prepare_b_prefix.h"

struct rf_core_rxon_b_bus {
    struct rf_core_rxon_prepare_bus registers;
    /* Shared original0x453c and0x3a7c; caller binds the correct RF-core ABI.
       Both use registers.context. No guessed CP/AP function-address calls.
       Historical name calibration below denotes table/context application,
       not a ready poll or lock check. Portable helper is available separately
       as rf_core_rxon_apply_tables(); the bus widths differ and need an adapter. */
    int (*calibration)(void *context, uint32_t rxon_context);
    int (*mode)(void *context, uint16_t mode);
};

/* Original B RXON body0x4ecc..0x5360, excludes ABI save/restore trampolines.
 * Precondition: exclusive RF context/register ownership; current request's
 * coefficients already produced in b520..b526; valid NV/table/route context.
 * Not a coefficient-generation or full cold-start API. All addresses RF-local.
 * Returns0, -1 invalid contract (no IO), -2 bus error, -3 calibration callback
 * failure, -4 mode callback failure. Failure stops immediately, no rollback.
 * Success means ordered calls/stores, not PLL lock, RF reception or DMA-ready.
 * Portable C preserves bus order, not cross-core instruction timing. Offline,
 * not linked into deployed capture service.
 */
int rf_core_rxon_b(const struct rf_core_rxon_b_bus *bus, uint32_t rxon_context);

struct rf_core_flow_bus;
/* Width-correct composition of the B body with actual portable0x453c table
 * application and0x3a7c mode implementation, not external helper callbacks.
 * Same initialized/exclusive context and precomputed coefficient contract.
 * Valid mode0..5 required by caller; preserves native repeated mode reads.
 * Returns0,-1 invalid bus,-2 body IO,-3 table helper failure,-4 mode failure.
 * No rollback or RF-lock promise. RF-local addresses only; no CP/AP bridge.
 * Offline, not linked/deployed; excludes caller/ABI/cold initialization. */
int rf_core_rxon_b_with_helpers(const struct rf_core_flow_bus *bus,
                                uint32_t rxon_context);

/* Shared RXON caller tail0x616e..0x6200 after either A/B and0x38a8.
 * Conditional original0xacc has timer/system MMIO side effects; retain it as
 * an explicit ABI-correct callback, not a guessed RF lock wait. Callback uses
 * registers.context and may update software state. All addresses RF-local.
 * Exclusive initialized context required. Returns0,-1 invalid bus/callback
 * (no IO),-2 bus failure,-3 helper failure. No rollback, no readiness promise.
 * Excludes subsequent calls at0x6202/0x620a and function epilogue. Offline only. */
struct rf_core_rxon_publish_bus {
    struct rf_core_rxon_prepare_bus registers;
    int (*shared_acc)(void *context);
};
int rf_core_rxon_publish_state(const struct rf_core_rxon_publish_bus *bus);

/* Original0xacc body0xad0..0xb52 including helper0x902. Records two packed
 * timer snapshots in five-entry RF-local rings; does not read PLL status.
 * Requires exclusive initialized state, valid0..4 indices at both92ce reads,
 * and a bus supporting literal system MMIO0x50090xxx as well as RF-local RAM.
 * Up to10 timer reads; original proceeds with last value even if busy stays
 * high. This is not a wait-for-lock, physical-time or timeout-success API.
 * Returns0,-1 invalid bus,-2 IO failure; no rollback. ABI trampolines excluded.
 * Offline only, not linked/deployed. */
int rf_core_rxon_record_timing(const struct rf_core_flow_bus *bus);
#endif
