#include "rf_core_tune_plan.h"

static void append(struct rf_core_write16 *output, uint32_t address, uint16_t value)
{
    output->local_address = address;
    output->value = value;
    output->reserved = 0;
}

int rf_core_make_retune_plan(const struct rf_core_tune_input *input,
                            struct rf_core_write16 *output, uint32_t capacity)
{
    uint32_t control, gate, q8_address, low_address, high_address, count = 0;
    uint16_t gate_before, gate_after, disabled;
    int has_mode_pair;

    if (!input || !output)
        return -1;
    if (input->polling_enabled)
        return -2;
    has_mode_pair = input->mode == 0 || input->mode == 6;
    if (capacity < (uint32_t)(has_mode_pair ? 11 : 9))
        return -1;

    if (input->selector <= 12 || input->selector == 17) {
        control = 0x30364;
        gate = 0x302cc;
        gate_before = 0x20;
        gate_after = 0x60;
        q8_address = 0x30360;
        low_address = 0x302c4;
        high_address = 0x302c8;
    } else {
        control = 0x30374;
        gate = 0x302e4;
        gate_before = 0xa0;
        gate_after = 0xe0;
        q8_address = 0x30370;
        low_address = 0x32228;
        high_address = 0x3222c;
    }
    disabled = input->control_before & (uint16_t)~0x80;
    append(output + count++, 0x30448, 0x805);
    append(output + count++, 0x32020, 0x1000);
    append(output + count++, control, disabled);
    append(output + count++, gate, gate_before);
    append(output + count++, q8_address, input->q8);
    append(output + count++, low_address, input->fraction_low);
    append(output + count++, high_address, input->fraction_high);
    if (has_mode_pair) {
        append(output + count++, 0x320fc, input->mode_pair_first);
        append(output + count++, 0x32100, input->mode_pair_second);
    }
    append(output + count++, control, disabled | 0x80);
    append(output + count++, gate, gate_after);
    return (int)count;
}
