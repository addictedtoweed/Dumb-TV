# start.S -- minimal crt0 for Dumb-TV SERV firmware.
#
# SERV resets its PC to 0, so _start must live at address 0 (the linker puts
# section .init first). Sets the stack pointer, zeroes .bss, calls main().
# Boilerplate -- firmware authors don't touch this.
#
# SPDX-License-Identifier: CC0-1.0

    .section .init, "ax"
    .global _start
_start:
    la      sp, _stack_top          # stack grows down from top of RAM

    la      t0, _bss_start          # zero .bss
    la      t1, _bss_end
1:  bgeu    t0, t1, 2f
    sw      zero, 0(t0)
    addi    t0, t0, 4
    j       1b
2:
    call    main
3:  j       3b                       # main returned: park the core
