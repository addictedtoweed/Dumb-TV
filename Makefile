# cocotb + Verilator build for the OSD compositor scaffold.
#
#   make            # run the testbench
#   make WAVES=1    # also dump dump.vcd (view with gtkwave)
#   make clean

TOPLEVEL_LANG ?= verilog
SIM           ?= verilator

PWD := $(shell pwd)

VERILOG_SOURCES = \
    $(PWD)/rtl/video_timing.v \
    $(PWD)/rtl/pattern_gen.v \
    $(PWD)/rtl/ctrl_regs.v \
    $(PWD)/rtl/osd_fb.v \
    $(PWD)/rtl/osd_compositor.v \
    $(PWD)/rtl/top.v \
    $(PWD)/rtl/uart_rx.v \
    $(PWD)/rtl/uart_tx.v \
    $(PWD)/rtl/cmd_parser.v \
    $(PWD)/rtl/top_uart.v

# Default target is the compositor pipeline. Run the UART suite with:
#   make TOPLEVEL=top_uart MODULE=test_uart
TOPLEVEL ?= top
MODULE   ?= test_compositor

export PYTHONPATH := $(PWD)/tb:$(PYTHONPATH)

ifeq ($(WAVES),1)
    EXTRA_ARGS += --trace --trace-structs
endif

include $(shell cocotb-config --makefiles)/Makefile.sim
