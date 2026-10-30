#include "rfad.h"

static uint32_t read32(const struct rf_bus *bus, uint32_t address)
{
    return bus->read(bus->context, address, 4);
}

static uint16_t read16(const struct rf_bus *bus, uint32_t address)
{
    return (uint16_t)bus->read(bus->context, address, 2);
}

static void write16(const struct rf_bus *bus, uint32_t address, uint16_t value)
{
    bus->write(bus->context, address, value, 2);
}

static void write32(const struct rf_bus *bus, uint32_t address, uint32_t value)
{
    bus->write(bus->context, address, value, 4);
}

static int event_index(uint32_t group, unsigned up)
{
    if (group >= 1 && group <= 14)
        return (int)group - 1;
    if (group >= 33 && group <= 44)
        return (int)group - 19;
    if (group == 47)
        return 26;
    if (!up) {
        if (group == 16 || group == 17)
            return (int)group + 11;
        if (group == 45 || group == 46)
            return (int)group - 16;
    }
    return -1;
}

static void clear_runtime(const struct rf_bus *bus, uint32_t table)
{
    uint32_t index;
    for (index = 0; index < 6690; ++index)
        write16(bus, table + 2 * index, 0);
}

static void build_events(const struct rf_bus *bus, uint32_t source, uint32_t table,
                         uint32_t command, unsigned up)
{
    uint16_t cursor = 0;
    uint16_t total = 0;
    uint16_t group_count = 0;
    uint32_t index;
    for (index = 0; index < 152; ++index) {
        uint32_t record = source + 8 * index;
        uint32_t header = read32(bus, record);
        uint16_t first = 0, count = 0;
        int event;
        if (((header >> 12) & 255) == 1) {
            uint32_t scan;
            for (scan = cursor; scan < 200; ++scan) {
                uint32_t action = source + 0x4c0 + 8 * scan;
                uint32_t head = read32(bus, action);
                if (head & 0xff000) {
                    uint32_t kind = (head >> 8) & 15;
                    unsigned end_group = kind == 15;
                    ++total;
                    if (kind == 1)
                        group_count = 0;
                    if (!end_group && scan + 1 < 200) {
                        uint32_t next = (read16(bus, action + 8) >> 8) & 15;
                        end_group = next != 8 && next != 15;
                    }
                    if (end_group) {
                        cursor = (uint16_t)(scan + 1);
                        break;
                    }
                    ++group_count;
                }
            }
            count = group_count;
            first = (uint16_t)(total - group_count + 151);
        }
        write16(bus, table + 0x31e4 + 2 * index, first);
        write16(bus, table + 0x3314 + 2 * index, count);
        event = event_index(header >> 24, up);
        if (event >= 0)
            rfad_bind_ram1(bus, table + 412 * (uint32_t)event + 84, record, command);
        if (read32(bus, record) & 0xff000)
            command += 4;
    }
}

static void build_actions(const struct rf_bus *bus, uint32_t source, uint32_t table,
                          uint32_t command, unsigned up)
{
    uint16_t cursor = 0, total = 0;
    uint32_t index;
    for (index = 0; index < 200; ++index) {
        uint32_t record = source + 0x4c0 + 8 * index;
        uint32_t header = read32(bus, record);
        uint16_t first = 0;
        int event;
        if (header & 0xff000) {
            if (((header >> 8) & 15) == 1) {
                uint32_t scan;
                for (scan = cursor; scan < 152; ++scan) {
                    uint32_t head = read32(bus, source + 8 * scan);
                    if (head & 0xff000) {
                        ++total;
                        if (((head >> 12) & 255) == 1) {
                            cursor = (uint16_t)(scan + 1);
                            break;
                        }
                    }
                }
            }
            first = (uint16_t)(total - 1);
        }
        event = event_index(header >> 24, up);
        if (event >= 0) {
            uint32_t address = table + 412 * (uint32_t)event;
            uint16_t count = read16(bus, address);
            write32(bus, address + 4 + 4 * count, record);
            rfad_bind_ram2(bus, address + 204, record, command, first);
            count = read16(bus, address);
            write16(bus, address, (uint16_t)(count + 1));
        }
        if (read32(bus, record) & 0xff000)
            command += 4;
    }
}

static void build_ram3(const struct rf_bus *bus, uint32_t source, uint32_t table, unsigned up)
{
    uint16_t cursor = 0, total = 0;
    uint32_t index;
    for (index = 0; index < 32; ++index) {
        uint32_t record = source + 0xb00 + 8 * index;
        uint32_t header = read32(bus, record);
        uint32_t group = header >> 24;
        uint16_t first = 0;
        int event;
        if (group) {
            uint32_t scan;
            for (scan = cursor; scan < 152; ++scan) {
                uint32_t head = read32(bus, source + 8 * scan);
                if (head & 0xff000) {
                    ++total;
                    if (((head >> 20) & 15) == 1) {
                        cursor = (uint16_t)(scan + 1);
                        break;
                    }
                }
            }
            first = (uint16_t)(total - 1);
        }
        event = event_index(group, up);
        if (event >= 0) {
            uint32_t address = table + 412 * (uint32_t)event + 404;
            if (group <= 9) {
                write32(bus, address, record);
                write16(bus, address + 4, first);
            } else {
                write16(bus, address + 4, first);
                write32(bus, address, record);
            }
        }
    }
}

void rfad_build_runtime(const struct rf_bus *bus, uint32_t nv, uint32_t down, uint32_t up)
{
    clear_runtime(bus, down);
    clear_runtime(bus, up);
    build_events(bus, nv + 0x20, down, RFAD_BASE + 0x1000, 0);
    build_actions(bus, nv + 0x20, down, RFAD_BASE + 0x1260, 0);
    build_ram3(bus, nv + 0x20, down, 0);
    build_events(bus, nv + 0xc20, up, RFAD_BASE + 0x2000, 1);
    build_actions(bus, nv + 0xc20, up, RFAD_BASE + 0x2260, 1);
    build_ram3(bus, nv + 0xc20, up, 1);
}

int rfad_validate_runtime_nv(const struct rf_bus *bus, uint32_t nv)
{
    unsigned direction;
    for (direction = 0; direction < 2; ++direction) {
        uint32_t source = nv + 0x20 + 0xc00 * direction;
        uint32_t index, cursor = 0;
        volatile uint8_t counts[31];
        for (index = 0; index < 31; ++index)
            counts[index] = 0;
        for (index = 0; index < 200; ++index) {
            uint32_t header = read32(bus, source + 0x4c0 + 8 * index);
            int event = event_index(header >> 24, direction);
            if (event >= 0 && ++counts[event] > 20)
                return -1;
        }
        for (index = 0; index < 152; ++index) {
            uint32_t header = read32(bus, source + 8 * index);
            if (((header >> 12) & 255) == 1) {
                uint32_t scan;
                unsigned started = 0, ended = 0;
                for (scan = cursor; scan < 200; ++scan) {
                    uint32_t action = source + 0x4c0 + 8 * scan;
                    uint32_t head = read32(bus, action);
                    if (head & 0xff000) {
                        uint32_t kind = (head >> 8) & 15;
                        uint32_t next = scan + 1 < 200 ? (read16(bus, action + 8) >> 8) & 15 : 8;
                        if (!started && kind != 1)
                            return -1;
                        started = 1;
                        if (kind == 15 || (scan + 1 < 200 && next != 8 && next != 15)) {
                            cursor = scan + 1;
                            ended = 1;
                            break;
                        }
                    }
                }
                if (!started || !ended)
                    return -1;
            }
        }
    }
    return 0;
}

int rfad_prepare_runtime(const struct rf_bus *bus, uint32_t nv, uint32_t down, uint32_t up)
{
    if (rfad_validate_runtime_nv(bus, nv))
        return -1;
    rfad_build_runtime(bus, nv, down, up);
    return 0;
}
