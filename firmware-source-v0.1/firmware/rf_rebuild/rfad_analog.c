#include "rfad_analog.h"

int rfad_prepare_analog(const struct rf_bus *bus, uint32_t nv, void *context,
                        int (*adi_write)(void *, uint32_t, uint32_t))
{
    if (!adi_write) return RFAD_ANALOG_INVALID;
    if (bus->read(bus->context, nv + 0x1a2cu, 2) == 1u) {
        uint32_t voltage = bus->read(bus->context, nv + 0x1a2eu, 2);
        if (voltage < 8u) voltage = 8u;
        else if (voltage >= 32u) voltage = 32u;
        if (adi_write(context, 0xc98u, voltage)) return RFAD_ANALOG_WRITE_FAILED;
    }
    uint32_t bypass = bus->read(bus->context, nv + 0x1a5cu, 4);
    if (adi_write(context, 0xc5cu, bypass == 0x5555u ? 0x90u : 0x80u))
        return RFAD_ANALOG_WRITE_FAILED;
    if (adi_write(context, 0xc68u, 1u)) return RFAD_ANALOG_WRITE_FAILED;
    if (adi_write(context, 0xc60u, 0x78u)) return RFAD_ANALOG_WRITE_FAILED;
    bus->write(bus->context, 0x50080054u, 0u, 4);
    bus->write(bus->context, 0x50300008u, 0x100u, 4);
    bus->write(bus->context, 0x50300034u, 3u, 4);
    bus->write(bus->context, 0x50300040u, 0xc60u, 4);
    bus->write(bus->context, 0x50300050u, 0x00780079u, 4);
    return RFAD_ANALOG_OK;
}
