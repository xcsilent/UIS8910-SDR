#include "rfad.h"

#define POWER UINT32_C(0x500a0000)

static uint32_t read32(const struct rf_bus *b, uint32_t a)
{
    return b->read(b->context, a, 4);
}

static void write32(const struct rf_bus *b, uint32_t a, uint32_t v)
{
    b->write(b->context, a, v, 4);
}

static int sample(const struct rf_bus *b, uint32_t a, uint32_t *budget, uint32_t *value)
{
    if (budget) {
        if (*budget == 0)
            return -1;
        --*budget;
    }
    *value = read32(b, a);
    return 0;
}

static void constraint(const struct rf_bus *b, const struct rfad_power_context *c, int enable)
{
    uint32_t saved = c->save_disable_irq(c->irq_context);
    uint32_t lock = read32(b, c->sleep_lock);
    lock = enable ? lock | UINT32_C(0x2000) : lock & ~UINT32_C(0x2000);
    write32(b, c->sleep_lock, lock);
    c->restore_irq(c->irq_context, saved);
}

static int phy(const struct rf_bus *b, const struct rfad_power_context *c,
               int enable, uint32_t *budget)
{
    uint32_t value;
    do {
        if (sample(b, POWER + 0x28, budget, &value))
            return RFAD_POWER_PHY_AVAILABLE_TIMEOUT;
    } while ((value & 2) == 0);
    if (sample(b, POWER + 0x28, budget, &value))
        return RFAD_POWER_PHY_STATE_TIMEOUT;
    uint32_t desired = enable ? 3 : 2;
    if (value != desired) {
        value = read32(b, POWER + 0xc);
        write32(b, POWER + 0xc, value | (enable ? 2u : 1u));
    }
    do {
        if (sample(b, POWER + 0x28, budget, &value))
            return RFAD_POWER_PHY_STATE_TIMEOUT;
    } while (value != desired);
    constraint(b, c, enable);
    return RFAD_POWER_OK;
}

static int zsp(const struct rf_bus *b, uint8_t poll, uint32_t *budget)
{
    write32(b, POWER + 0x54, poll);
    uint32_t value;
    do {
        if (sample(b, POWER + 0x24, budget, &value))
            return RFAD_POWER_ZSP_TIMEOUT;
    } while (value != 3);
    return RFAD_POWER_OK;
}

static void erc_setup(const struct rf_bus *b)
{
    write32(b, POWER + 0x3c, 0x20);
    write32(b, POWER + 0x40, 0x70);
    write32(b, POWER + 0x44, 0x100);
}

void rfad_initialize_idle_words(const struct rf_bus *b)
{
    write32(b, UINT32_C(0x500900c4), 0x7800);
    write32(b, UINT32_C(0x500900f0), 0x7800);
}

void rfad_zsp_open(const struct rf_bus *b, uint8_t poll)
{
    (void)zsp(b, poll, 0);
}

void rfad_zsp_close(const struct rf_bus *b, uint8_t poll)
{
    write32(b, POWER + 0x50, poll);
}

void rfad_lte_phy_open(const struct rf_bus *b, const struct rfad_power_context *c)
{
    (void)phy(b, c, 1, 0);
}

void rfad_lte_phy_close(const struct rf_bus *b, const struct rfad_power_context *c)
{
    (void)phy(b, c, 0, 0);
}

void rfad_erc_domains_open(const struct rf_bus *b, const struct rfad_power_context *c)
{
    erc_setup(b);
    rfad_lte_phy_open(b, c);
    rfad_zsp_open(b, 6);
}

int rfad_erc_domains_open_checked(const struct rf_bus *b, const struct rfad_power_context *c,
                                  uint32_t budget)
{
    if (budget == 0)
        return RFAD_POWER_INVALID_BUDGET;
    erc_setup(b);
    int status = phy(b, c, 1, &budget);
    if (status != RFAD_POWER_OK)
        return status;
    return zsp(b, 6, &budget);
}
