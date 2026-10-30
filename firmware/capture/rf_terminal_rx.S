/* The only returning path has not taken RF/DMA ownership. A claimed finite
 * transaction remains IRQ/FIQ masked until AP reset, including on errors. */
.syntax unified
.cpu cortex-a5
.thumb
#include "terminal_asm_binding.h"
.section .text.entry,"ax",%progbits
.global terminal_native_entry
.type terminal_native_entry,%function
.thumb_func
terminal_native_entry:
    push.w {r0-r12,lr}
    mrs r0,cpsr
    cpsid if
    push {r0,r1}
    mov r4,sp
    ldr sp,=TERM_STACK_TOP
    push {r4,r5}
    mov r0,r4
    bl terminal_dispatch
    cpsid if
    pop {r4,r5}
    mov sp,r4
    pop {r0,r1}
    msr cpsr_fsxc,r0
    pop.w {r0-r12,lr}
    push.w {r3,r4,r5,r6,r7,r8,r9,lr}
    mov r4,r1
    ldr lr,=TERM_MAIN_CONTINUE
    ldr.w pc,=TERM_CALC_ENTRY
    .ltorg
.size terminal_native_entry,.-terminal_native_entry

/* The monitor's CP_CALL already masks IRQ/FIQ. Use the same private aligned
 * stack when trying the ownership gate between FCP events. A busy attempt
 * returns to CP_CALL; a claimed transaction uses terminal_hold as usual. */
.global terminal_foreground_entry
.type terminal_foreground_entry,%function
.thumb_func
terminal_foreground_entry:
    push.w {r4-r11,lr}
    mov r4,sp
    ldr sp,=TERM_STACK_TOP
    push {r4,lr}
    sub sp,sp,#16
    mrs r0,cpsr
    str r0,[sp]
    movs r0,#0
    str r0,[sp,#4]
    str r0,[sp,#8]
    str r0,[sp,#12]
    mov r0,sp
    bl terminal_dispatch
    cpsid if
    add sp,sp,#16
    pop {r4,r5}
    mov sp,r4
    pop.w {r4-r11,pc}
    .ltorg
.size terminal_foreground_entry,.-terminal_foreground_entry

.section .text.hold,"ax",%progbits
.global terminal_hold
.type terminal_hold,%function
.thumb_func
terminal_hold:
    cpsid if
1:  dsb sy
    wfi
    b 1b
.size terminal_hold,.-terminal_hold
