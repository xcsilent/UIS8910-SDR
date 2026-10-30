#ifndef RXCAPT_STREAM_PROTOCOL_H
#define RXCAPT_STREAM_PROTOCOL_H

/* DBG_RX_STREAM request: {version, maximum service duration in ms, generation}.
 * Reply payload starts with eight LE u32 words:
 * {magic, kind, packet sequence, block sequence, offset, total, flags, auxiliary}.
 * ACCEPT auxiliary is the CP queue sequence. BLOCK total is 8024 bytes, with
 * DATA[8000] followed by HEAD[24]; flags bit 0 marks the last chunk.
 * END adds eight counters {blocks, DATA bytes, HEAD bytes, elapsed ms,
 * CP sequence, parked, terminal phase, terminal error}, then the eight words
 * of the actual CP PARK response (zero when not parked). END auxiliary is the
 * CP stop reason; flags are the final CP stream flags. Outer UDG1 status is
 * nonzero on a failed session. Queue acceptance never certifies RF start.
 */
#define RXS_VERSION 1u
#define RXS_MAGIC 0x32535852u /* RXS2 */
#define RXS_ACCEPT 1u
#define RXS_BLOCK 2u
#define RXS_END 3u
#define RXS_HEADER_BYTES 32u
#define RXS_DATA_BYTES 8000u
#define RXS_HEAD_BYTES 24u
#define RXS_PAIR_BYTES (RXS_DATA_BYTES+RXS_HEAD_BYTES)
#define RXS_SLOTS 7u
#define RXS_GENERATION 0x5246001au
#define RXS_STATE_ADDRESS 0x8096fa40u
#define RXS_PROGRESS_ADDRESS 0x8096fec0u
#define RXS_DATA_ADDRESS 0x80960000u
#define RXS_HEAD_ADDRESS 0x8096ff00u
#define RXS_STATE_MAGIC 0x53545231u
#define RXS_SERVICE_MAGIC 0x52585331u
#define RXS_PROGRESS_MAGIC 0x54524d31u
#define RXS_COMMAND_TIMEOUT_MS 1000u
#define RXS_INITIALIZE_TIMEOUT_MS 5000u
#define RXS_DRAIN_TIMEOUT_MS 5000u

#endif
