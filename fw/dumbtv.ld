/* dumbtv.ld -- linker script for Dumb-TV SERV firmware.
 *
 * One 16 KB program RAM at address 0 (matches serv_soc MEMSIZE). The whole
 * image is loaded verbatim over FW_WRITE, so .data initial values are already
 * in place; crt0 only has to zero .bss. Boilerplate -- don't touch.
 *
 * SPDX-License-Identifier: CC0-1.0
 */
OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY
{
    RAM (rwx) : ORIGIN = 0x00000000, LENGTH = 16K
}

SECTIONS
{
    .text : {
        *(.init)                /* _start must be first (PC resets to 0) */
        *(.text .text.*)
    } > RAM

    .rodata : {
        *(.rodata .rodata.*)
        *(.srodata .srodata.*)
    } > RAM

    .data : {
        *(.data .data.*)
        *(.sdata .sdata.*)
    } > RAM

    .bss : {
        . = ALIGN(4);
        _bss_start = .;
        *(.bss .bss.*)
        *(.sbss .sbss.*)
        *(COMMON)
        . = ALIGN(4);
        _bss_end = .;
    } > RAM

    . = ALIGN(4);
    _stack_top = ORIGIN(RAM) + LENGTH(RAM);

    /DISCARD/ : { *(.comment) *(.riscv.attributes) }
}
