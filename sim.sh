#!/usr/bin/env bash
# Convenience runner: activates the cocotb venv and runs a make target with a
# space-free build directory (Verilator refuses to build under a path
# containing spaces, e.g. ".../IP Freely/...").
#
#   ./sim.sh                                       # compositor tests
#   ./sim.sh TOPLEVEL=top_uart MODULE=test_uart    # UART control-plane tests
set -e
source ~/dumbtv-venv/bin/activate
cd "$(dirname "$0")"

# Pick a distinct build dir per top-level so switching suites never uses a
# stale build. Override by exporting SIM_BUILD yourself.
case "$*" in
    *top_uart*) : "${SIM_BUILD:=/tmp/dumbtv_build_uart}" ;;
    *top_rgb*)  : "${SIM_BUILD:=/tmp/dumbtv_build_rgb}" ;;
    *top_mux*)  : "${SIM_BUILD:=/tmp/dumbtv_build_mux}" ;;
    *serv_soc*) : "${SIM_BUILD:=/tmp/dumbtv_build_servsoc}" ;;
    *serv_ram*) : "${SIM_BUILD:=/tmp/dumbtv_build_servram}" ;;
    *)          : "${SIM_BUILD:=/tmp/dumbtv_build_top}" ;;
esac
export SIM_BUILD

make "$@"
