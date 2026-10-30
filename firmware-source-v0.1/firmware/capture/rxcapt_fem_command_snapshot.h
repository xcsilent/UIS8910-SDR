#ifndef RXCAPT_FEM_COMMAND_SNAPSHOT_H
#define RXCAPT_FEM_COMMAND_SNAPSHOT_H
#include <stdint.h>

/* ABI4 tail: two 20-word rows, at words 88..127 of the existing 512-byte
 * trace. These fixed observations do not write RFAD or establish execution. */
#define FEM_COMMAND_COUNT 5u
#define FEM_COMMAND_ROW_WORDS 20u
#define FEM_COMMAND_TAIL_WORD 88u

static int fem_command_pointer_valid(uint32_t address)
{
    return !(address & 3u) &&
        ((address >= 0x25101260u && address <= 0x2510157cu) ||
         (address >= 0x25102260u && address <= 0x2510257cu));
}

/* Caller provides the only memory read primitive. It must be used from CP
 * with the RFAD controller powered; rejected pointers are never dereferenced. */
typedef uint32_t (*fem_snapshot_read32)(void *context, uint32_t address);
static void fem_command_observe(uint32_t *row, uint32_t stage,
                                fem_snapshot_read32 read32, void *context)
{
    static const uint32_t objects[FEM_COMMAND_COUNT] = {
        0x804ee978u, 0x804efcc8u, 0x804edc98u, 0x804ee4a4u, 0x804ef320u
    };
    for (unsigned i = 0; i < FEM_COMMAND_ROW_WORDS; ++i) row[i] = 0;
    row[0] = stage;
    for (unsigned i = 0; i < FEM_COMMAND_COUNT; ++i) {
        uint32_t pointer = read32(context, objects[i] + 0x2cu);
        row[1u + 3u*i] = pointer;
        if (fem_command_pointer_valid(pointer)) {
            row[2u + 3u*i] = read32(context, pointer);
            row[3u + 3u*i] = 1u;
        }
    }
}
#endif
