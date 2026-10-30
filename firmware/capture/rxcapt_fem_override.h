#ifndef RXCAPT_FEM_OVERRIDE_H
#define RXCAPT_FEM_OVERRIDE_H
#if defined(RXCAPT_EXPERIMENTAL_FEM_OVERRIDE) && RXCAPT_EXPERIMENTAL_FEM_OVERRIDE
#include "rf_frontend_override.h"
/* Private CP metadata words40..43 hold recovery state; word44 is result.
 * The control module clears all64 words on first install. Never clear active
 * on REARM/error. RF alias access follows the existing CP device view, with
 * DSB ordering. No AP/RF concurrent writers are allowed during the experiment.
 */
static uint32_t terminal_fem_read(void *c,uint32_t a,unsigned n) {
    uint32_t value=raw_read(c,a,n);
    __asm__ volatile("dsb sy":::"memory");return value;
}
static void terminal_fem_write(void *c,uint32_t a,uint32_t v,unsigned n) {
    raw_write(c,a,v,n);__asm__ volatile("dsb sy":::"memory");
}
static __attribute__((noinline)) int terminal_fem_begin(uint32_t row) {
    struct rf_frontend_override *s=(struct rf_frontend_override *)(TERM_META+160u);
    const struct rf_bus bus={0,terminal_fem_read,terminal_fem_write};
    uint32_t mode=CFG[11];int result=0;
    if(s->active || mode>2u)result=RF_FEM_OVERRIDE_INVALID;
    else if(mode)result=rf_frontend_override_apply(&bus,s,row,mode==1u?2u:5u,1u);
    M[44]=(uint32_t)result;clean_range(TERM_META+160u,32u);return result;
}
static __attribute__((noinline)) int terminal_fem_end(void) {
    struct rf_frontend_override *s=(struct rf_frontend_override *)(TERM_META+160u);
    const struct rf_bus bus={0,terminal_fem_read,terminal_fem_write};
    int result=s->active?rf_frontend_override_restore(&bus,s,1u):0;
    M[44]=(uint32_t)result;clean_range(TERM_META+160u,32u);return result;
}
#else
static int terminal_fem_begin(uint32_t row) {(void)row;return 0;}
static int terminal_fem_end(void) {return 0;}
#endif
#endif
