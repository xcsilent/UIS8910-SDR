#ifndef RXCAPT_REUSE_PROTOCOL_H
#define RXCAPT_REUSE_PROTOCOL_H
/* Opcode34 request: six LE u32 {version, duration_ms, generation,
 * expected_last_command, raw_frequency, stop_after_pairs}.
 * Duration starts after REARM acknowledgement (includes RF preparation).
 * stop_after_pairs is a STOP threshold, not a hard output limit: in-flight
 * pairs are drained and exported. Zero selects duration-only operation.
 * ACCEPT adds {epoch,raw_frequency,rearm_command,version}; END adds the same
 * four words after the legacy eight counters and eight IDLE-response words.
 * USB retries may replay END only. They do not replay old IQ or repeat RF.
 */
#define RXR_OPERATION 34u
#define RXR_VERSION 1u
#define RXR_TRACE_ADDRESS 0x8096e000u
#define RXR_FREQUENCY_ADDRESS 0x8096fa00u
#define RXR_ANCHOR_RAW 23300000u
#define RXR_SEQUENCE_LIMIT 0xfff00000u
typedef struct {
 uint32_t duration,last_command,raw,stop_pairs,epoch,cp_sequence,heartbeat,response_sequence;
} rxr_request_t;
#endif
