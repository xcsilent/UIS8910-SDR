.syntax unified
.cpu cortex-a5
.thumb
.section .text.gateway,"ax"
.global cp_gateway
.thumb_func
cp_gateway:
 ldr r0, =0x80970000
 ldr r1, [r0]
 ldr r2, =0x31424455
 cmp r1, r2
 bne 1f
 dmb sy
 ldr r3, [r0, #4]
 cbz r3, 1f
 bx r3
1: bx lr
 .balign 4
 .ltorg
