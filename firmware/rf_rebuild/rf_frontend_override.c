#include "rf_frontend_override.h"

static int valid_bus(const struct rf_bus *b) {
    return b && b->read && b->write;
}
static int valid_state(const struct rf_frontend_override *s) {
    return s && s->active == 1u &&
        ((s->address == 0x500097f0u && s->original == 0x000d0005u) ||
         (s->address == 0x50009810u && s->original == 0x000d0002u)) &&
        (s->replacement == 0x000d0002u || s->replacement == 0x000d0005u);
}
int rf_frontend_override_apply(const struct rf_bus *b,
    struct rf_frontend_override *s, uint32_t row, uint32_t value, uint32_t idle)
{
    if (!valid_bus(b) || !s || s->active || (row != 4u && row != 6u) ||
        (value != 2u && value != 5u) || idle != 1u)
        return RF_FEM_OVERRIDE_INVALID;
    uint32_t address = row == 4u ? 0x500097f0u : 0x50009810u;
    uint32_t original = row == 4u ? 0x000d0005u : 0x000d0002u;
    /* Require v28 helper signature, published config pointer, known source
     * command AND its RF copy. Row numbers alone are insufficient guards.
     * The immutable runtime NV is read for identity only, never written.
     */
    if (b->read(b->context,0x500010e8u,4) != 0x0120506fu ||
        b->read(b->context,0x50007e18u,4) != 0x96b0u ||
        b->read(b->context,0x804f42b8u+0x20u+2u*row,2) != (row==4u?5u:8u) ||
        b->read(b->context,0x804f42b8u+0x310u+16u*row,4) != original ||
        b->read(b->context,address,4) != original)
        return RF_FEM_OVERRIDE_CONTEXT;
    s->address=address; s->original=original;
    s->replacement=0x000d0000u|value; s->active=1u;
    /* Record recovery state BEFORE writing. A failed readback is not proof
     * that a write failed, so retain active ownership on all such failures.
     */
    b->write(b->context,address,value,1);
    return b->read(b->context,address,4)==s->replacement ?
        RF_FEM_OVERRIDE_OK : RF_FEM_OVERRIDE_READBACK;
}
int rf_frontend_override_restore(const struct rf_bus *b,
    struct rf_frontend_override *s, uint32_t idle)
{
    if (!valid_bus(b) || !valid_state(s) || idle != 1u)
        return RF_FEM_OVERRIDE_INVALID;
    uint32_t live=b->read(b->context,s->address,4);
    if (live != s->original && live != s->replacement)
        return RF_FEM_OVERRIDE_CONFLICT;
    if (live != s->original)
        b->write(b->context,s->address,s->original&255u,1);
    if (b->read(b->context,s->address,4) != s->original)
        return RF_FEM_OVERRIDE_READBACK;
    s->active=0u;
    return RF_FEM_OVERRIDE_OK;
}
