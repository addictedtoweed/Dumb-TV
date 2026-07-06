# cocotb + Verilator build for the OSD compositor scaffold.
#
#   make            # run the testbench
#   make WAVES=1    # also dump dump.vcd (view with gtkwave)
#   make clean

TOPLEVEL_LANG ?= verilog
SIM           ?= verilator

# Relative paths on purpose: absolute paths break `make` when the repo lives
# under a directory containing a space (e.g. "IP Freely").
VERILOG_SOURCES = \
    rtl/video_timing.v \
    rtl/pattern_gen.v \
    rtl/ctrl_regs.v \
    rtl/osd_fb.v \
    rtl/osd_compositor.v \
    rtl/top.v \
    rtl/uart_rx.v \
    rtl/uart_tx.v \
    rtl/cmd_parser.v \
    rtl/top_uart.v \
    rtl/sync2.v \
    rtl/rgb_in.v \
    rtl/top_rgb.v

# Default target is the compositor pipeline. Run the UART suite with:
#   make TOPLEVEL=top_uart MODULE=test_uart
TOPLEVEL ?= top
MODULE   ?= test_compositor

export PYTHONPATH := $(CURDIR)/tb:$(PYTHONPATH)

# Width-expansion/truncation in ordinary arithmetic is benign here; don't let
# Verilator treat those (noisy) warnings as fatal. Real lint (implicit nets,
# etc.) stays fatal via `default_nettype none` in the RTL.
EXTRA_ARGS += -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC

ifeq ($(WAVES),1)
    EXTRA_ARGS += --trace --trace-structs
endif

include $(shell cocotb-config --makefiles)/Makefile.sim
