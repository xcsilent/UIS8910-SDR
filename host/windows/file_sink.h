#ifndef SDR_FILE_SINK_H
#define SDR_FILE_SINK_H
#include <stdint.h>

typedef struct sdr_file_sink sdr_file_sink;
struct sdr_file_stats {
    uint64_t queued_bytes,written_bytes,dropped_bytes,queue_full_events;
    uint32_t error,high_water_blocks,pending_blocks;
    double writer_cpu_seconds,drain_seconds;
};
/* One receiving thread enqueues; a separate writer owns the slot until its
 * WriteFile ends. Short inputs accumulate directly in an owned block; full
 * blocks or blocks that cannot fit the next input are published to the writer.
 * Close publishes the last partial block. One host memcpy, no sample processing
 * or stream framing; block_bytes limits batching latency in byte units only.
 * Full queues discard the incoming block and count it; errors return nonzero.
 */
uint32_t sdr_file_sink_open(sdr_file_sink **,const char *,uint32_t block_bytes,uint32_t blocks);
int sdr_file_sink_push(sdr_file_sink *,const void *,uint32_t bytes);
uint32_t sdr_file_sink_error(sdr_file_sink *);
/* Drain queued writes, then cancel on timeout. Never release storage while a
 * writer may reference it. On unresolved timeout *sink stays alive; close may
 * be retried. This bounds observation, not the OS completion of disk I/O. */
uint32_t sdr_file_sink_close(sdr_file_sink **,struct sdr_file_stats *,uint32_t drain_ms);
#endif
