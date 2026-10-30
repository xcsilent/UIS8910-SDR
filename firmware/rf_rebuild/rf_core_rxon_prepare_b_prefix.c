#include "rf_core_rxon_prepare_b_prefix.h"

int rf_core_rxon_clock_mode(const struct rf_core_rxon_prepare_bus *bus, uint16_t mode)
{
    uint16_t selector, middle=0x511fu, last=0x517fu;
    if (!bus || !bus->read16 || !bus->write16) return -1;
    if (mode>6u) return 0;
    if (mode==4u || mode==5u) {
        if (bus->read16(bus->context,0xb538u,&selector)) return -2;
        if (selector==5u || selector==15u) { middle=0x508fu; last=0x50ffu; }
    }
    if (bus->write16(bus->context,0x30350u,0x501fu)) return -2;
    if (mode!=6u && bus->write16(bus->context,0x30350u,middle)) return -2;
    /* Two native NOPs between middle/last: preserves the explicit operations,
       not RF-clock timing when compiled for another processor. */
    __asm__ volatile("nop\nnop":::"memory");
    if (bus->write16(bus->context,0x30350u,mode==6u ? 0x507fu : last)) return -2;
    return 0;
}

int rf_core_rxon_prepare_b_enter(const struct rf_core_rxon_prepare_bus *bus,
    uint32_t rxon_context, struct rf_core_rxon_b_saved *saved)
{
    struct rf_core_rxon_b_saved value;
    uint16_t flag,field,word,old;
    if (!bus || !bus->read16 || !bus->write16 || !saved) return -1;
#define READ(a,v) do { if (bus->read16(bus->context,(a),&(v))) return -2; } while (0)
#define WRITE(a,v) do { if (bus->write16(bus->context,(a),(uint16_t)(v))) return -2; } while (0)
    READ(0x30400u,value.reg400); READ(0x30404u,value.reg404);
    WRITE(0x30364u,0x33); WRITE(0x302ccu,0x20);
    READ(0xb52au,flag);
    if (!flag) {
        WRITE(0x30498u,2); WRITE(0x304c0u,0);
        READ(rxon_context+4u,field); READ(0x8a54u+10u*field+6u,word);
        WRITE(0x30480u,word);
    } else {
        READ(0x30480u,old);
        READ(rxon_context+4u,field); READ(0x8a54u+10u*field+6u,word);
        WRITE(0x30480u,old|word);
    }
    WRITE(0x30320u,0x501f);
    *saved=value;
#undef READ
#undef WRITE
    return 0;
}

int rf_core_rxon_prepare_b_commit(const struct rf_core_rxon_prepare_bus *bus)
{
    uint16_t word;
    if (!bus || !bus->read16 || !bus->write16) return -1;
#define READ(a,v) do { if (bus->read16(bus->context,(a),&(v))) return -2; } while (0)
#define WRITE(a,v) do { if (bus->write16(bus->context,(a),(uint16_t)(v))) return -2; } while (0)
    READ(0xb520u,word); WRITE(0x30360u,word);
    READ(0xb524u,word); WRITE(0x302c4u,word);
    READ(0xb522u,word); WRITE(0x302c8u,word);
#undef READ
#undef WRITE
    return 0;
}

int rf_core_rxon_prepare_b_prefix(const struct rf_core_rxon_prepare_bus *bus,
                                   uint32_t rxon_context)
{
    uint16_t word, factor, field;
    uint32_t row;
    if (!bus || !bus->read16 || !bus->write16) return -1;
#define READ(a,v) do { if (bus->read16(bus->context,(a),&(v))) return -2; } while (0)
#define WRITE(a,v) do { if (bus->write16(bus->context,(a),(uint16_t)(v))) return -2; } while (0)
    READ(0x30410u,word); READ(0xb526u,factor);
    WRITE(0x30410u,(word & 0x87ffu) | ((uint32_t)factor << 11));
    READ(0x302c0u,word); READ(0xb526u,factor);
    WRITE(0x302c0u,(word & 0xfffcu) | ((uint32_t)factor - 7u));
    WRITE(0x3041cu,0x11c0); WRITE(0x30420u,0x5861);
    WRITE(0x30424u,0x7208); WRITE(0x30408u,0x4845);
    READ(rxon_context+4u,field); row=0x8a54u+10u*field;
    READ(row,word); WRITE(0x30418u,word);
    READ(rxon_context+4u,field); row=0x8a54u+10u*field;
    READ(row+2u,word); WRITE(0x3040cu,word);
    READ(0x3049cu,word); word &= 0x8000u;
    READ(rxon_context+4u,field); row=0x8a54u+10u*field;
    READ(row+4u,factor); WRITE(0x3049cu,word | factor);
    READ(rxon_context+4u,field); row=0x8a54u+10u*field;
    READ(row+8u,word); WRITE(0x30414u,word);
    READ(rxon_context+4u,field); READ(0x8184u+2u*field,word);
    WRITE(0x30468u,word);
#undef READ
#undef WRITE
    return 0;
}
