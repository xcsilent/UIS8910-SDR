#ifndef RF_CORE_RXON_REQUEST_H
#define RF_CORE_RXON_REQUEST_H
#include <stdint.h>

struct rf_core_rxon_words {
    uint16_t mode_selector, auxiliary, frequency_low, frequency_high;
    uint16_t zfif_flag;
    int16_t correction_mode0[4], correction_mode6[4];
};
struct rf_core_rxon_request {
    uint32_t requested_raw, working_raw;
    uint16_t mode, field4, selector, correction_index, slot, context16;
};

/* Pure decoding of RV 0x602c..0x6121. This does not initialize hardware.
 * Reject a selected out-of-table ZFIF index before publishing the output. */
int rf_core_decode_rxon_request(const struct rf_core_rxon_words *in,
                                struct rf_core_rxon_request *out);

struct rf_core_flow_bus;
/* Offline original RXON0x602c through coefficient generation/dispatch and B
 * body0x5360 with actual helpers. mode0..5, B selectors0..12/17, valid port/NV
 * tables and slot0..14, exclusive initialized RF ownership required. Reads
 * four RFAD halfwords; publishes context, mode0 ZFIF correction, Q8/factor/
 * fraction in native order, then B body. Physical100Hz/clock meaning and live
 * request freshness are caller concerns. No AP/CP address bridge supplied.
 * Returns-1 unsupported/invalid arithmetic or request (may follow context
 * writes),-2 IO/body failure,-3 table helper,-4 mode helper. No rollback.
 * Excludes ABI/caller post-configure/cold start. Not linked or deployed. */
int rf_core_rxon_request_b(const struct rf_core_flow_bus *bus);
#endif
