ENTRY(cp_agent_poll)
SECTIONS {
 . = 0x80971000;
 .text : { KEEP(*(.text.entry)) *(.text*) *(.rodata*) }
 .data : { *(.data*) }
 .bss : { *(.bss*) *(COMMON) }
 ASSERT(SIZEOF(.bss) == 0, "agent must have no implicit BSS initialization")
 ASSERT(. <= 0x80975000, "agent exceeds reservation")
 /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) }
}
