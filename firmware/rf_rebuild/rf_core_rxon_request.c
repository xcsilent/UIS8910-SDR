#include "rf_core_rxon_request.h"
#include "rf_core_tune_flow.h"
#include "rf_core_frequency.h"
#include "rf_core_rxon_b.h"

static void decode_fields(const struct rf_core_rxon_words *in,
                           struct rf_core_rxon_request *out)
{
    struct rf_core_rxon_request r;
    r.mode = in->mode_selector & 15u;
    /* Original EXTRACTU at0x606a extracts four bits7:4, not three bits6:4.
       Preserving a decoded value does not validate it as an analog-table row. */
    r.field4 = (in->mode_selector >> 4) & 15u;
    r.selector = (in->mode_selector >> 8) & 31u;
    /* Original EXTRACTU at0x6080 extracts two bits14:13. This differs
       from the separate retune argument's one-bit index at0x6390. */
    r.correction_index = (in->mode_selector >> 13) & 3u;
    r.slot = in->auxiliary >> 12;
    r.context16 = in->auxiliary & 4095u;
    r.requested_raw = ((uint32_t)in->frequency_high << 16) | in->frequency_low;
    r.working_raw = r.requested_raw;
    *out = r;
}

int rf_core_decode_rxon_request(const struct rf_core_rxon_words *in,
                                struct rf_core_rxon_request *out)
{
    struct rf_core_rxon_request r;
    int16_t correction = 0;
    if (!in || !out) return -1;
    decode_fields(in,&r);
    if (r.mode == 0u) {
        if ((in->mode_selector & 0x8000u) || r.selector <= 12u || r.selector == 17u)
            r.correction_index = in->zfif_flag;
        if (r.correction_index >= 4u)
            return -1;
        correction = in->correction_mode0[r.correction_index];
    } else if (r.mode == 6u) {
        correction = in->correction_mode6[r.correction_index];
    }
    r.working_raw = r.requested_raw + (uint32_t)(int32_t)correction;
    *out = r;
    return 0;
}

int rf_core_rxon_request_b(const struct rf_core_flow_bus *bus)
{
    struct rf_core_rxon_words words;
    struct rf_core_rxon_request r;
    struct rf_core_frequency_words frequency;
    struct rf_core_frequency_coefficients coefficients;
    uint32_t value;uint16_t flag,index,correction,state,factor=7,lookup;
    if(!bus || !bus->read || !bus->write)return -1;
#define READ16(a,v) do { if(bus->read(bus->context,(a),2,&value))return -2;(v)=(uint16_t)value; } while(0)
#define READ32(a,v) do { if(bus->read(bus->context,(a),4,&(v)))return -2; } while(0)
#define WRITE(a,w,v) do { if(bus->write(bus->context,(a),(w),(v)))return -2; } while(0)
    READ16(0x30050u,words.mode_selector);READ16(0x30054u,words.auxiliary);
    READ16(0x30058u,words.frequency_low);READ16(0x30008u,words.frequency_high);
    decode_fields(&words,&r);
    if(r.mode>5u || !(r.selector<=12u || r.selector==17u) || r.slot>14u)return -1;
    WRITE(0xb530u,2,r.mode);WRITE(0xb534u,2,r.field4);WRITE(0xb538u,2,r.selector);
    WRITE(0xb550u,2,r.correction_index);WRITE(0xb544u,2,r.slot);WRITE(0xb546u,2,r.context16);
    WRITE(0xb53cu,4,r.requested_raw);
    if(!r.mode) {
        /* B selectors always take the original ZFIF override, then re-read
         * the stored index. Do not move this read before context publication. */
        READ16(0xb4deu,flag);WRITE(0xb550u,2,flag);READ16(0xb550u,index);
        if(index>=4u)return -1;
        READ16(0x7b70u+2u*index,correction);
        r.working_raw=r.requested_raw+(uint32_t)(int32_t)(int16_t)correction;
        WRITE(0xb53cu,4,r.working_raw);
    }
    READ32(0xb53cu,frequency.working_raw);
    /* Original0x37f0 publishes Q8 BEFORE it reads the MDLL state/table. */
    frequency.factor_state=0;frequency.table_factor=7;
    if(rf_core_frequency_coefficients(&frequency,&coefficients))return -1;
    WRITE(0xb520u,2,coefficients.q8);
    READ16(0xa710u,state);
    if(state==1u) {
        READ16(0x940cu+2u*r.selector,lookup);
        READ16(0xa714u+2u*lookup,factor);
    }
    WRITE(0xb526u,2,factor);READ16(0xb526u,factor);
    if(!factor)return -1;
    frequency.factor_state=1;frequency.table_factor=factor;
    if(rf_core_frequency_coefficients(&frequency,&coefficients))return -1;
    WRITE(0xb524u,2,coefficients.fraction_low);WRITE(0xb522u,2,coefficients.fraction_high);
    READ16(0xb538u,index);
    if(!(index<=12u || index==17u))return -1;
#undef READ16
#undef READ32
#undef WRITE
    return rf_core_rxon_b_with_helpers(bus,0xb530u);
}
