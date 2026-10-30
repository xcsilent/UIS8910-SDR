#ifndef RXCAPT_STREAM_BATCH_H
#define RXCAPT_STREAM_BATCH_H
#include <stdint.h>

/* Optional CP service operations 11/12. ABI 1 ring metadata is retained:
 * first claim block -> claim all currently ready contiguous blocks;
 * exclusive end block -> release one contiguous USB-completed prefix.
 * No sample data is read. Caller serializes this with the CP DMA poller.
 */
uint32_t rxcapt_stream_claim_batch(volatile uint32_t *, uint32_t first, uint32_t *end);
uint32_t rxcapt_stream_release_batch(volatile uint32_t *, uint32_t end);
/* Validate the entire prefix before mutation, release [released,release_end),
 * and claim all READY rows after already-held rows. Empty release/claim is
 * legal. Return the exclusive claimed end. Caller serializes with DMA; this
 * is only a metadata primitive, not an enabled mailbox operation by itself. */
uint32_t rxcapt_stream_exchange_batch(volatile uint32_t *,uint32_t release_end,uint32_t *claim_end);
#endif
