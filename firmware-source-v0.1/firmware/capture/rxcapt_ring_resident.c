#include <stdint.h>
#include "rxcapt_finite_abi.h"
#include "rxcapt_finite_binding.h"
#include "rxcapt_stream_idle.h"

/* The terminal worker masks IRQ/FIQ while it owns the RF and DMA path, so it
 * must poll completed channels and re-arm them itself. Seven blocks stop
 * before the service's state/evidence area at 0x8096f800. */
#ifndef RXCAPT_RING_BLOCKS
#define RXCAPT_RING_BLOCKS 7u
#endif
#define RXCAPT_RING_DATA_BASE 0x80960000u
#define RXCAPT_RING_DATA_LIMIT 0x8096f800u
#define RXCAPT_RING_HEAD_BASE 0x8096ff00u
#define RXCAPT_RING_HEAD_LIMIT 0x80970000u
#define RXCAPT_RING_HEAD_BLOCK_BYTES 24u
#define RXCAPT_DMA_IRQ_STATUS (*(volatile uint32_t *)0x2200000cu)
#define RXCAPT_DMA_RUN_MASK 0x00000001u
#define RXCAPT_DMA_INTERRUPT_STATUS_MASK 0x0000000eu
#define RXCAPT_DMA_COUNT_FINISH_STATUS 0x00200000u
#define RXCAPT_DMA_RESPONSE_ERROR_MASK 0x06000000u
#define RXCAPT_REGS ((volatile uint32_t *)0x27000000u)

typedef void (*rxcap_dma_start_fn)(uint32_t, uint32_t, const uint32_t *);

static uint32_t dma_base(uint32_t channel) {
    if (channel < 7u || channel > 9u) return 0u;
    uint32_t base = ((volatile const uint32_t *)
                     RXCAPT_DMA_CHANNEL_TABLE_ADDRESS)[channel];
    if ((base & 3u) || base < 0x22000000u || base >= 0x22100000u)
        return 0u;
    return base;
}

static uint32_t rearm(uint32_t channel, uint32_t is_head, uint32_t slot) {
    if (slot >= RXCAPT_RING_BLOCKS) return 0u;
    uint32_t base = dma_base(channel);
    if (!base) return 0u;

    volatile uint32_t *dma = (volatile uint32_t *)base;
    uint32_t status = dma[6];
    if (dma[4] != 0u || !(status & RXCAPT_DMA_COUNT_FINISH_STATUS) ||
        (status & (RXCAPT_DMA_RUN_MASK | RXCAPT_DMA_RESPONSE_ERROR_MASK)))
        return 0u;

    uint32_t channel_bit = 1u << channel;
    uint32_t pending = RXCAPT_DMA_IRQ_STATUS & channel_bit;
    if (pending) RXCAPT_DMA_IRQ_STATUS = pending;
    dma[6] = status & (RXCAPT_DMA_INTERRUPT_STATUS_MASK |
                       RXCAPT_DMA_COUNT_FINISH_STATUS);
    __asm__ volatile("dsb sy" ::: "memory");

    uint32_t destination;
    uint32_t length;
    volatile uint32_t *globals =
        (volatile uint32_t *)RXCAPT_GLOBALS_ADDRESS;
    volatile uint32_t *descriptor;
    if (is_head) {
        length = RXCAPT_RING_HEAD_BLOCK_BYTES;
        destination = RXCAPT_RING_HEAD_BASE + slot * length;
        if (destination + length > RXCAPT_RING_HEAD_LIMIT) return 0u;
        globals[2] = destination;
        globals[3] = length;
        descriptor = (volatile uint32_t *)RXCAPT_HEAD_DESCRIPTOR_ADDRESS;
    } else {
        length = RXCAPT_FINITE_DATA_BYTES;
        destination = RXCAPT_RING_DATA_BASE + slot * length;
        if (destination + length > RXCAPT_RING_DATA_LIMIT) return 0u;
        globals[0] = destination;
        globals[1] = length;
        descriptor = (volatile uint32_t *)RXCAPT_DATA_DESCRIPTOR_ADDRESS;
    }
    descriptor[3] = destination;
    descriptor[4] = length;
    descriptor[5] = length;
    __asm__ volatile("dmb sy" ::: "memory");
    ((rxcap_dma_start_fn)RXCAPT_DMA_START_ENTRY)(
        2u, channel, (const uint32_t *)descriptor);
    return 1u;
}

__attribute__((noinline))
uint32_t rxcapt_ring_poll_rearm(uint32_t channel, uint32_t is_head,
                                uint32_t next_slot) {
    if (is_head > 1u) return 0u;
    return rearm(channel, is_head, next_slot);
}

/* Streaming-ring metadata ABI. The caller owns a 30-word region in CP RAM:
 * header[0..8], then seven {sequence, active_mask, done_mask} slot records.
 * active_mask bits 0/1 are DATA/HEAD DMA ownership and bit 2 is AP reading.
 * A slot remains unavailable until AP releases its monotonically ordered seq. */
#define STREAM_MAGIC 0x53545231u
#define STREAM_VERSION 1u
#define STREAM_WORDS 30u
#define STREAM_HEADER_WORDS 9u
#define STREAM_SLOT_WORDS 3u
#define STREAM_FREE 0xffffffffu
#define STREAM_STOP 1u
#define STREAM_FULL 2u
#define STREAM_HOST_STOP 1u
#define STREAM_RING_FULL 2u
#define STREAM_SEQUENCE_END 3u
#define STREAM_DMA_MASK 3u
#define STREAM_HOST_MASK 4u

static volatile uint32_t *stream_slot(volatile uint32_t *state, uint32_t slot) {
    return state + STREAM_HEADER_WORDS + STREAM_SLOT_WORDS * slot;
}

static int stream_valid(volatile uint32_t *state) {
    return state && state[0] == STREAM_MAGIC &&
           state[1] == STREAM_VERSION && state[2] >= 2u &&
           state[2] <= RXCAPT_RING_BLOCKS &&
           STREAM_HEADER_WORDS + STREAM_SLOT_WORDS * state[2] <= STREAM_WORDS;
}

__attribute__((noinline))
uint32_t rxcapt_stream_state_init(volatile uint32_t *state, uint32_t slots) {
    if (!state || slots < 2u || slots > RXCAPT_RING_BLOCKS ||
        STREAM_HEADER_WORDS + STREAM_SLOT_WORDS * slots > STREAM_WORDS)
        return 0u;
    for (uint32_t i = 0; i < STREAM_WORDS; ++i) state[i] = 0u;
    state[0] = STREAM_MAGIC;
    state[1] = STREAM_VERSION;
    state[2] = slots;
    state[4] = 0u; /* active DATA sequence */
    state[5] = 0u; /* active HEAD sequence */
    state[6] = 0u; /* first not-yet-published paired sequence */
    state[7] = 0u; /* first not-yet-released sequence */
    for (uint32_t i = 0; i < slots; ++i) {
        volatile uint32_t *row = stream_slot(state, i);
        row[0] = STREAM_FREE;
        row[1] = 0u;
        row[2] = 0u;
    }
    volatile uint32_t *first = stream_slot(state, 0u);
    first[0] = 0u;
    first[1] = STREAM_DMA_MASK;
    __asm__ volatile("dmb sy" ::: "memory");
    return 1u;
}

static void stream_advance_publish(volatile uint32_t *state) {
    uint32_t slots = state[2];
    for (uint32_t i = 0; i < slots; ++i) {
        uint32_t sequence = state[6];
        volatile uint32_t *row = stream_slot(state, sequence % slots);
        if (row[0] != sequence || row[1] != 0u || row[2] != STREAM_DMA_MASK)
            break;
        state[6] = sequence + 1u;
    }
}

/* Complete one channel's active block. Return 1 and next_slot when the DMA
 * channel may re-arm, 2 when a host STOP is draining, 3 on a full ring, 0 on
 * inconsistent state. Completion publishes only paired DATA+HEAD records. */
__attribute__((noinline))
uint32_t rxcapt_stream_complete(volatile uint32_t *state, uint32_t channel,
                               uint32_t sequence, uint32_t *next_slot) {
    if (next_slot) *next_slot = STREAM_FREE;
    if (!stream_valid(state) || channel > 1u || !next_slot) return 0u;
    uint32_t bit = 1u << channel;
    uint32_t current_index = channel ? 5u : 4u;
    if (state[current_index] != sequence) return 0u;
    uint32_t slots = state[2];
    volatile uint32_t *current = stream_slot(state, sequence % slots);
    if (current[0] != sequence || !(current[1] & bit) ||
        (current[2] & bit)) return 0u;
    current[1] &= ~bit;
    current[2] |= bit;
    stream_advance_publish(state);

    if (state[3] & STREAM_STOP) {
        __asm__ volatile("dmb sy" ::: "memory");
        return 2u;
    }

    uint32_t following = sequence + 1u;
    uint32_t slot = following % slots;
    volatile uint32_t *target = stream_slot(state, slot);
    if (target[0] == following) {
        /* The opposite DMA channel may already have reserved this sequence. */
    } else if (target[0] == STREAM_FREE && target[1] == 0u && target[2] == 0u) {
        target[0] = following;
        target[1] = 0u;
        target[2] = 0u;
    } else {
        state[3] |= STREAM_STOP | STREAM_FULL;
        state[8] = STREAM_RING_FULL;
        __asm__ volatile("dmb sy" ::: "memory");
        return 3u;
    }
    if ((target[1] & bit) || (target[2] & bit)) return 0u;
    target[1] |= bit;
    state[current_index] = following;
    *next_slot = slot;
    __asm__ volatile("dmb sy" ::: "memory");
    return 1u;
}

__attribute__((noinline))
uint32_t rxcapt_stream_next_ready(volatile uint32_t *state,
                                 uint32_t *sequence, uint32_t *slot) {
    if (!stream_valid(state) || !sequence || !slot || state[7] == state[6])
        return 0u;
    uint32_t ready = state[7];
    uint32_t index = ready % state[2];
    volatile uint32_t *row = stream_slot(state, index);
    if (row[0] != ready || row[1] != 0u || row[2] != STREAM_DMA_MASK)
        return 0u;
    *sequence = ready;
    *slot = index;
    return 1u;
}

__attribute__((noinline))
uint32_t rxcapt_stream_claim(volatile uint32_t *state, uint32_t sequence) {
    if (!stream_valid(state) || sequence != state[7] || sequence == state[6])
        return 0u;
    volatile uint32_t *row = stream_slot(state, sequence % state[2]);
    if (row[0] != sequence || row[1] != 0u || row[2] != STREAM_DMA_MASK)
        return 0u;
    row[1] |= STREAM_HOST_MASK;
    __asm__ volatile("dmb sy" ::: "memory");
    return 1u;
}

__attribute__((noinline))
uint32_t rxcapt_stream_release(volatile uint32_t *state, uint32_t sequence) {
    if (!stream_valid(state) || sequence != state[7] || sequence == state[6])
        return 0u;
    volatile uint32_t *row = stream_slot(state, sequence % state[2]);
    if (row[0] != sequence || row[1] != STREAM_HOST_MASK ||
        row[2] != STREAM_DMA_MASK) return 0u;
    row[0] = STREAM_FREE;
    row[1] = 0u;
    row[2] = 0u;
    state[7] = sequence + 1u;
    __asm__ volatile("dmb sy" ::: "memory");
    return 1u;
}

__attribute__((noinline))
uint32_t rxcapt_stream_request_stop(volatile uint32_t *state) {
    if (!stream_valid(state)) return 0u;
    if (!(state[3] & STREAM_STOP)) state[8] = STREAM_HOST_STOP;
    state[3] |= STREAM_STOP;
    __asm__ volatile("dmb sy" ::: "memory");
    return 1u;
}

__attribute__((noinline))
uint32_t rxcapt_stream_request_stop_reason(volatile uint32_t *state,
                                          uint32_t reason) {
    if (!stream_valid(state)) return 0u;
    if (!(state[3] & STREAM_STOP)) state[8] = reason;
    state[3] |= STREAM_STOP;
    __asm__ volatile("dmb sy" ::: "memory");
    return 1u;
}

/* Call only after the hardware stop/restore path has made both DMA channels
 * inactive. Keep completed READY pairs visible; discard only partial writers. */
__attribute__((noinline))
uint32_t rxcapt_stream_dma_aborted(volatile uint32_t *state,
                                  uint32_t reason) {
    if (!stream_valid(state)) return 0u;
    state[3] |= STREAM_STOP;
    state[8] = reason;
    for (uint32_t i = 0; i < state[2]; ++i)
        stream_slot(state, i)[1] &= ~STREAM_DMA_MASK;
#if defined(RXCAPT_LOSSY_SCRATCH) && RXCAPT_LOSSY_SCRATCH
    if (state[2] == 6u) stream_slot(state, 6u)[1] &= ~STREAM_DMA_MASK;
#endif
    __asm__ volatile("dmb sy" ::: "memory");
    return 1u;
}

__attribute__((noinline))
uint32_t rxcapt_stream_dma_idle(volatile uint32_t *state) {
    if (!stream_valid(state)) return 0u;
#if defined(RXCAPT_LOSSY_SCRATCH) && RXCAPT_LOSSY_SCRATCH
    return rxcapt_rows_dma_idle(state, 1u);
#else
    for (uint32_t i = 0; i < state[2]; ++i)
        if (stream_slot(state, i)[1] & STREAM_DMA_MASK) return 0u;
    return 1u;
#endif
}

static void unexpected_callback(void) {
    volatile rxcapt_finite_state_t *state =
        (volatile rxcapt_finite_state_t *)RXCAPT_FINITE_STATE_ADDRESS;
    if (state->magic == RXCAPT_FINITE_MAGIC &&
        state->phase == RXCAPT_PHASE_RUNNING) {
        state->error = 0x220u;
        state->phase = RXCAPT_PHASE_FAILED;
        RXCAPT_REGS[1] &= ~1u;
        RXCAPT_REGS[4] &= ~3u;
        __asm__ volatile("dsb sy" ::: "memory");
    }
}

/* Interrupts are masked by terminal_dispatch. If that ownership contract is
 * ever broken, stop safely instead of racing the polled re-arm loop. */
__attribute__((section(".text.callback")))
void rxcapt_finite_data_callback(uint32_t channel, uint32_t events) {
    (void)channel;
    (void)events;
    unexpected_callback();
}

__attribute__((section(".text.callback")))
void rxcapt_finite_head_callback(uint32_t channel, uint32_t events) {
    (void)channel;
    (void)events;
    unexpected_callback();
}
