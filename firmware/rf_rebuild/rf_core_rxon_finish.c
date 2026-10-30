#include "rf_core_rxon_finish.h"

/* Original0x453c applies table/context values; it does not poll ready/VCO. */
int rf_core_rxon_apply_tables(const struct rf_core_rxon_finish_bus *bus,
                             uint32_t rxon_context)
{
    uint32_t selector,slot,word,mode;
    if (!bus || !bus->read || !bus->write) return -1;
#define READ(a,n,v) do { if (bus->read(bus->context,(a),(n),&(v))) return -2; } while (0)
#define WRITE(a,n,v) do { if (bus->write(bus->context,(a),(n),(v)&65535u)) return -2; } while (0)
    /* Entire 0x453c helper, including each original context re-read. */
    READ(rxon_context+8u,2,selector); READ(rxon_context+0x14u,2,slot);
    READ(0x8764u+2u*(15u*selector+slot),2,word); WRITE(0x30448u,2,word);
    READ(rxon_context,2,mode); WRITE(0x3044cu,2,mode==6u ? 0x9534 : 0xad34);
    READ(rxon_context+0x16u,2,word); WRITE(0x32020u,2,word | 0x1000u);
    WRITE(0x32128u,2,0x1000); WRITE(0x32008u,2,1); WRITE(0x3201cu,2,0x0a02);
    READ(rxon_context+8u,2,selector); READ(rxon_context+0x14u,2,slot);
    READ(0x9438u+2u*(15u*selector+slot),2,word); WRITE(0x30474u,2,word);
    READ(rxon_context+8u,2,selector); READ(rxon_context+0x14u,2,slot);
    READ(0xaf78u+4u*(15u*selector+slot),2,word); WRITE(0x3200cu,2,word);
    READ(rxon_context+8u,2,selector); READ(rxon_context+0x14u,2,slot);
    READ(0xaf7au+4u*(15u*selector+slot),2,word); WRITE(0x32010u,2,word);

#undef READ
#undef WRITE
    return 0;
}


int rf_core_rxon_finish_a(const struct rf_core_rxon_finish_bus *bus,
                         uint32_t rxon_context, uint32_t ready_budget,
                         uint32_t timer_budget,
                         struct rf_core_rxon_finish_result *result)
{
    uint32_t flag, word, field, saved, mode, factor;
    if (!result) return -1;
    result->stage=RF_FINISH_INITIAL;
    result->ready_reads=result->timer_reads=0;
    result->timer_timeout_cleanup_complete=0;
    if (!bus || !bus->read || !bus->write || !bus->mode ||
        !ready_budget || !timer_budget) return -1;
#define READ(a,n,v) do { if (bus->read(bus->context,(a),(n),&(v))) return -2; } while (0)
#define WRITE(a,n,v) do { if (bus->write(bus->context,(a),(n),(v)&((n)==2 ? 65535u : 0xffffffffu))) return -2; } while (0)
    READ(0xb464u,2,flag);
    if (flag) {
        result->stage=RF_FINISH_READY;
        do {
            READ(0x3037cu,2,word); ++result->ready_reads;
            if (word & 0x800u) break;
        } while (result->ready_reads < ready_budget);
        if (!(word & 0x800u)) return -3;
        result->stage=RF_FINISH_TIMER;
        READ(0x38000u,4,word); WRITE(0x38000u,4,word & ~11u);
        WRITE(0x38004u,4,0);
        /* Original 0x6ac returns 122880000; 0x760 divides BEFORE multiplying
         * by delay argument 1: reload is exactly integer 122, not 123. */
        WRITE(0x38008u,4,122); WRITE(0x3800cu,4,1); WRITE(0x38000u,4,11);
        do {
            READ(0x3800cu,4,word); ++result->timer_reads;
            if (word & 1u) break;
        } while (result->timer_reads < timer_budget);
        if (!(word & 1u)) {
            result->stage=RF_FINISH_TIMER_CLEANUP;
            WRITE(0x3800cu,4,1); READ(0x38000u,4,word);
            WRITE(0x38000u,4,word & ~11u);
            result->timer_timeout_cleanup_complete=1;
            return -4;
        }
        WRITE(0x3800cu,4,1); READ(0x38000u,4,word);
        WRITE(0x38000u,4,word & ~11u);
        READ(0x30454u,2,word); WRITE(0x30454u,2,word | 0x130u);
    }
    result->stage=RF_FINISH_LATCH;
    READ(0x304b4u,2,saved); WRITE(0x30498u,2,7);
    READ(0xb534u,2,field); READ(0x84f6u+8u*field,2,word);
    WRITE(0x30414u,2,word | 0x40u);
    WRITE(0x304b4u,2,saved & ~0x200u); WRITE(0x302e4u,2,0xe0);
    READ(0xb534u,2,field); READ(0x84f6u+8u*field,2,word);
    WRITE(0x30414u,2,word | 0x60u); WRITE(0x304b4u,2,saved | 0x200u);

    result->stage=RF_FINISH_CALIBRATION;
    if (rf_core_rxon_apply_tables(bus,rxon_context)) return -2;

    result->stage=RF_FINISH_MODE;
    READ(rxon_context,2,mode);
    if (bus->mode(bus->context,mode)) return -5;
    result->stage=RF_FINISH_FINAL;
    READ(0xb464u,2,flag);
    if (flag) {
        WRITE(0x31040u,2,2); WRITE(0x31040u,2,3);
        READ(0xb526u,2,factor);
        WRITE(0x32a00u,2,((factor-7u)<<6) | 0xffff9007u);
    }
    result->stage=RF_FINISH_COMPLETE;
#undef READ
#undef WRITE
    return 0;
}
