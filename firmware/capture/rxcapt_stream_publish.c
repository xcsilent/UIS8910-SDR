#include <stdint.h>
#include "terminal_binding.h"

/* The producer owns private metadata. AP reads a published copy. In particular,
 * public STOP cannot precede the final RF/DMA teardown and final pair count. */
void terminal_stream_publish(void) {
    volatile const uint32_t *state=(volatile const uint32_t *)RXCAPT_STREAM_STATE_ADDRESS;
    volatile uint32_t *out=(volatile uint32_t *)RXCAPT_STREAM_EXPORT_ADDRESS;
    uint32_t address=(uint32_t)out;
    out[0]=0;out[3]=0;
    __asm__ volatile("dmb sy\nmcr p15,0,%0,c7,c10,1\ndsb sy"::"r"(address):"memory");
    for(unsigned i=0;i<30u;i++)if(i!=0u && i!=3u)out[i]=state[i];
    for(uint32_t line=address;line<address+120u;line+=32u)
        __asm__ volatile("mcr p15,0,%0,c7,c10,1"::"r"(line):"memory");
    __asm__ volatile("dsb sy":::"memory");
    uint32_t phase=*(volatile uint32_t *)(TERM_META+12u);
    out[0]=state[0];
    out[3]=state[3]&((phase==30u || phase==31u)?0xffffffffu:~1u);
    __asm__ volatile("dmb sy\nmcr p15,0,%0,c7,c10,1\ndsb sy"::"r"(address):"memory");
}
