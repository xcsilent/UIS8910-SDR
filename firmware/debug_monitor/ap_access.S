.syntax unified
.cpu cortex-a5
.section .text.debug_access,"ax"
.thumb
.global debug_load_word
.thumb_func
debug_load_word:
 cmp r1, #4
 beq load32
 cmp r1, #2
 beq load16
load8: ldrb r3, [r0]
 b load_done
load16: ldrh r3, [r0]
 b load_done
load32: ldr r3, [r0]
load_done:
 str r3, [r2]
 movs r0, #1
 bx lr
.global debug_store_word
.thumb_func
debug_store_word:
 cmp r1, #4
 beq store32
 cmp r1, #2
 beq store16
store8: strb r2, [r0]
 b store_done
store16: strh r2, [r0]
 b store_done
store32: str r2, [r0]
store_done:
 dsb sy
 movs r0, #1
 bx lr
access_fail:
 movs r0, #0
 bx lr

/* Bounded, aligned copy of already CLAIMed RXCAPT RAM into AP staging.
 * No stack frame or callee-saved registers, so access_fail returns directly.
 * Only the source load is recoverable; destination is known AP staging RAM. */
.global debug_copy_words
.type debug_copy_words,%function
.thumb_func
debug_copy_words:
 cbz r2, copy_done
copy_load:
 ldr r3, [r0], #4
 str r3, [r1], #4
 subs r2, r2, #1
 bne copy_load
copy_done:
 movs r0, #1
 bx lr
.size debug_copy_words, .-debug_copy_words

#ifdef DBG_ENABLE_RX_STREAM_BURST
/* Fixed claimed RAM only. 32-byte groups and an exact word tail. Prefetch is
 * issued only when its address is inside the remaining source range. */
.global debug_copy_words_burst
.type debug_copy_words_burst,%function
.thumb_func
debug_copy_words_burst:
 push {r4-r10,lr}
 cmp r2, #8
 blo burst_tail
burst_loop:
 cmp r2, #64
 blo burst_load
 pld [r0, #128]
burst_load:
 ldmia r0!, {r3-r10}
 stmia r1!, {r3-r10}
 subs r2, r2, #8
 cmp r2, #8
 bhs burst_loop
burst_tail:
 cbz r2, burst_done
burst_tail_load:
 ldr r3, [r0], #4
 str r3, [r1], #4
 subs r2, r2, #1
 bne burst_tail_load
burst_done:
 movs r0, #1
 pop {r4-r10,pc}
burst_fail:
 movs r0, #0
 pop {r4-r10,pc}
.size debug_copy_words_burst, .-debug_copy_words_burst
#endif

/* The vector branches here in Abort mode. Recover only precise faults at our
 * six isolated access instructions; preserve the original platform handler otherwise. */
.arm
.balign 4
.global debug_data_abort_gate
.type debug_data_abort_gate,%function
debug_data_abort_gate:
 push {r0-r3}
 sub r0, lr, #8
 ldr r1, =load8
 cmp r0, r1
 beq access_recover
 ldr r1, =load16
 cmp r0, r1
 beq access_recover
 ldr r1, =load32
 cmp r0, r1
 beq access_recover
 ldr r1, =store8
 cmp r0, r1
 beq access_recover
 ldr r1, =store16
 cmp r0, r1
 beq access_recover
 ldr r1, =store32
 cmp r0, r1
 beq access_recover
 ldr r1, =copy_load
 cmp r0, r1
 beq access_recover
#ifdef DBG_ENABLE_RX_STREAM_BURST
 ldr r1, =burst_load
 cmp r0, r1
 beq burst_recover
 ldr r1, =burst_tail_load
 cmp r0, r1
 beq burst_recover
#endif
 pop {r0-r3}
 ldr pc, =0x0080022c
access_recover:
 ldr lr, =access_fail
 pop {r0-r3}
 movs pc, lr
#ifdef DBG_ENABLE_RX_STREAM_BURST
burst_recover:
 ldr lr, =burst_fail
 pop {r0-r3}
 movs pc, lr
#endif
 .ltorg
