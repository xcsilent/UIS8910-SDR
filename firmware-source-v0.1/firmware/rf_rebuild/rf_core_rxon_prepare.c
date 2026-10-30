#include "rf_core_rxon_prepare.h"

int rf_core_rxon_prepare_a(const struct rf_core_rxon_prepare_bus *bus,
                           uint32_t rxon_context)
{
    uint16_t word, factor, field, flag, mode, selector, saved;
    uint32_t row;
    if (!bus || !bus->read16 || !bus->write16)
        return -1;
#define READ(a,v) do { if (bus->read16(bus->context,(a),&(v))) return -2; } while (0)
#define WRITE(a,v) do { if (bus->write16(bus->context,(a),(uint16_t)(v))) return -2; } while (0)
    WRITE(0x32238u,0);
    READ(0x30410u,word); READ(0xb526u,factor);
    WRITE(0x30410u,(word & 0x87ffu) | ((uint32_t)factor << 11));
    READ(0x302e0u,word); READ(0xb526u,factor);
    WRITE(0x302e0u,(word & 0xfffcu) | ((uint32_t)factor - 7u));
    WRITE(0x3040cu,0x1060);
    READ(0xb4d0u,word); WRITE(0x3042cu,0x50e8u + (word & 15u));
    WRITE(0x30434u,0x11c0); WRITE(0x30438u,0x5861);
    READ(0x3049cu,word); WRITE(0x3049cu,(word & 0x8000u) | 0x17f0u);
    READ(0xaf70u,saved); READ(0xb534u,field);
    row=0x84f0u + 8u * field; READ(row,word); WRITE(0x304c0u,word | saved);
    READ(0xb534u,field); row=0x84f0u + 8u * field;
    READ(row+2u,word); WRITE(0x30480u,word);
    READ(0x92ccu,flag); READ(0xb534u,field);
    row=(flag ? 0x84b0u : 0x84f0u) + 8u * field;
    READ(row+4u,word); WRITE(0x30430u,word);
    READ(0xb534u,field); row=0x84f0u + 8u * field;
    READ(row+6u,word); WRITE(0x30414u,word);
    READ(0xb534u,field); READ(0x8184u+2u*field,word); WRITE(0x30468u,word);
    READ(rxon_context,mode);
    if (!mode) {
        WRITE(0x3046cu,0x3c00); WRITE(0x30478u,0x0400);
    } else {
        WRITE(0x3046cu,((uint32_t)mode << 13) | 0x1c03u);
        READ(rxon_context,mode); WRITE(0x30478u,((uint32_t)mode << 10) | 0x180u);
    }
    WRITE(0x3047cu,0x328e); READ(rxon_context,mode);
    if (mode <= 2u) {
        WRITE(0x304b4u,0x0a53); WRITE(0x304b8u,0x2c88);
    } else {
        READ(rxon_context+8u,selector);
        if (selector==5u || selector==15u) {
            WRITE(0x304b4u,0x0a4d); WRITE(0x304b8u,0x2888);
        } else {
            WRITE(0x304b4u,0x0a57); WRITE(0x304b8u,0x2088);
        }
    }
    READ(0xb464u,flag);
    if (flag) { WRITE(0x304acu,3); WRITE(0x30464u,0x143b); }
    else WRITE(0x30464u,0x001a);
    WRITE(0x30400u,0xc382); WRITE(0x30498u,6); READ(rxon_context,mode);
    WRITE(0x30404u,mode<=3u ? 0xb804 : 0xb014);
    WRITE(0x30374u,0x00b3);
#undef READ
#undef WRITE
    return 0;
}
