MEMORY {
  FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
  RAM (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
}
_estack = ORIGIN(RAM) + LENGTH(RAM);
ENTRY(Reset_Handler)
SECTIONS {
 .isr_vector : { KEEP(*(.isr_vector)) } > FLASH
 .text : { *(.text*) *(.rodata*) . = ALIGN(4); } > FLASH
 .data : AT(LOADADDR(.text) + SIZEOF(.text)) {
     . = ALIGN(4); _sdata = .; *(.data*) . = ALIGN(4); _edata = .;
 } > RAM
 _sidata = LOADADDR(.data);
 .bss (NOLOAD) : { . = ALIGN(4); _sbss = .; *(.bss*) *(COMMON) . = ALIGN(4); _ebss = .; } > RAM
 /DISCARD/ : { *(.comment*) *(.ARM.exidx*) *(.eh_frame*) *(.note*) }
}
