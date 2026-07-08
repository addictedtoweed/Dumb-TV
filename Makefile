# cocotb + Verilator build for the OSD compositor scaffold.
#
#   make            # run the testbench
#   make WAVES=1    # also dump dump.vcd (view with gtkwave)
#   make clean

TOPLEVEL_LANG ?= verilog
SIM           ?= verilator

# OSD canvas storage backend: bram (on-chip, default) or psram (external memory).
#   make CANVAS=psram ...
CANVAS ?= bram

# Relative paths on purpose: absolute paths break `make` when the repo lives
# under a directory containing a space (e.g. "IP Freely").
VERILOG_SOURCES = \
    rtl/video_timing.v \
    rtl/pattern_gen.v \
    rtl/ctrl_regs.v \
    rtl/pwm.v \
    rtl/osd_fb_$(CANVAS).v \
    rtl/palette.v \
    rtl/osd_compositor.v \
    rtl/top.v \
    rtl/uart_rx.v \
    rtl/uart_tx.v \
    rtl/glyph_store.v \
    rtl/cmd_parser.v \
    rtl/top_uart.v \
    rtl/sync2.v \
    rtl/rgb_in.v \
    rtl/top_rgb.v \
    rtl/fifo.v \
    rtl/cmd_mux.v \
    rtl/fw_mem.v \
    rtl/top_mux.v \
    rtl/serv_ram_hw.v

# Default target is the compositor pipeline. Run the UART suite with:
#   make TOPLEVEL=top_uart MODULE=test_uart
TOPLEVEL ?= top
MODULE   ?= test_compositor

# The vendored SERV core is only pulled in for the serv_soc build, so its lint
# doesn't affect the other suites.
ifeq ($(TOPLEVEL),serv_soc)
VERILOG_SOURCES += rtl/serv_soc.v \
    $(wildcard rtl/serv/serv_top.v rtl/serv/serv_state.v rtl/serv/serv_decode.v \
               rtl/serv/serv_immdec.v rtl/serv/serv_bufreg.v rtl/serv/serv_bufreg2.v \
               rtl/serv/serv_ctrl.v rtl/serv/serv_alu.v rtl/serv/serv_rf_if.v \
               rtl/serv/serv_mem_if.v rtl/serv/serv_csr.v rtl/serv/serv_aligner.v \
               rtl/serv/serv_compdec.v rtl/serv/serv_rf_ram.v rtl/serv/serv_rf_ram_if.v) \
    $(wildcard rtl/serv/servile*.v) \
    rtl/serv/servant_mux.v rtl/serv/servant_timer.v rtl/serv/servant_gpio.v
# SERV is Verilator-clean but uses different lint conventions; don't be fatal.
EXTRA_ARGS += -Wno-fatal
endif

export PYTHONPATH := $(CURDIR)/tb:$(PYTHONPATH)

# Width-expansion/truncation in ordinary arithmetic is benign here; don't let
# Verilator treat those (noisy) warnings as fatal. Real lint (implicit nets,
# etc.) stays fatal via `default_nettype none` in the RTL.
EXTRA_ARGS += -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC

ifeq ($(WAVES),1)
    EXTRA_ARGS += --trace --trace-structs
endif

include $(shell cocotb-config --makefiles)/Makefile.sim
