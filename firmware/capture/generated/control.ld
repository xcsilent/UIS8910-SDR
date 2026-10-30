ENTRY(terminal_control)
SECTIONS {
 . = 0;
 .text : { KEEP(*(.text.entry)) *(.text*) *(.rodata*) }
 .data : { *(.data*) }
 .bss : { *(.bss*) *(COMMON) }
 ASSERT(SIZEOF(.data) == 0, "RAM module has implicit initialized data")
 ASSERT(SIZEOF(.bss) == 0, "RAM module has implicit BSS")
 ASSERT(. <= 0x2000, "RAM module exceeds one slot")
 /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) }
}
