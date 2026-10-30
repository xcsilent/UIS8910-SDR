#include "rf_core_rxon_prepare_b_mode.h"

int rf_core_rxon_prepare_b_mode(const struct rf_core_rxon_prepare_bus *bus,
    uint32_t rxon_context, uint16_t saved_400, uint16_t saved_404)
{
    uint16_t mode, flag, selector;
    if (!bus || !bus->read16 || !bus->write16) return -1;
#define READ(a,v) do { if (bus->read16(bus->context,(a),&(v))) return -2; } while (0)
#define WRITE(a,v) do { if (bus->write16(bus->context,(a),(uint16_t)(v))) return -2; } while (0)
    READ(rxon_context,mode);
    if (mode==6u) {
        WRITE(0x3046cu,0x1cf8); WRITE(0x30478u,0);
    } else if (!mode) {
        WRITE(0x3046cu,0x3c00); WRITE(0x30478u,0x0400);
    } else {
        READ(0xb4e0u,flag);
        if (flag) {
            WRITE(0x3046cu,((uint32_t)mode<<13)|0x1c00u);
            READ(rxon_context,mode); WRITE(0x30478u,(uint32_t)mode<<10);
        } else {
            WRITE(0x3046cu,((uint32_t)mode<<13)|0x1c03u);
            READ(rxon_context,mode); WRITE(0x30478u,((uint32_t)mode<<10)|0x0180u);
        }
    }
    READ(rxon_context,mode); WRITE(0x3047cu,mode==6u ? 0x228e : 0x328e);
    READ(rxon_context,mode);
    if (mode<=2u) {
        WRITE(0x304b4u,0); WRITE(0x304b8u,0);
    } else {
        READ(rxon_context+8u,selector);
        if (selector==5u || selector==15u) {
            WRITE(0x304b4u,0x0a4d); WRITE(0x304b8u,0x2888);
        } else {
            WRITE(0x304b4u,0x0a57); WRITE(0x304b8u,0x2088);
        }
    }
    WRITE(0x30400u,saved_400|0xc000u);
    READ(0xb52au,flag); if (!flag) WRITE(0x30498u,6);
    READ(rxon_context,mode);
    WRITE(0x30404u,saved_404|((mode==6u || mode<=3u) ? 0xbf05u : 0xb715u));
#undef READ
#undef WRITE
    return 0;
}
