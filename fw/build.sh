#!/usr/bin/env bash
# build.sh -- compile a Dumb-TV SERV firmware source into a flat binary.
#
#   ./build.sh [source.c] [outname]
#   ./build.sh                       # -> example.c -> firmware.bin
#
# Produces <outname>.elf and <outname>.bin. The .bin is the 16 KB-max image you
# upload over the serial link (host/dumbtv.py load_firmware).
#
# Needs a bare-metal RISC-V toolchain:
#   sudo apt install gcc-riscv64-unknown-elf
set -e

CC=${CC:-riscv64-unknown-elf-gcc}
OBJCOPY=${OBJCOPY:-riscv64-unknown-elf-objcopy}
SIZE=${SIZE:-riscv64-unknown-elf-size}

SRC=${1:-example.c}
OUT=${2:-firmware}
DIR="$(cd "$(dirname "$0")" && pwd)"

"$CC" -march=rv32i -mabi=ilp32 -nostdlib -nostartfiles -ffreestanding \
      -Os -Wall -Wextra -fomit-frame-pointer \
      -T "$DIR/dumbtv.ld" "$DIR/start.S" "$SRC" -o "$OUT.elf"
"$OBJCOPY" -O binary "$OUT.elf" "$OUT.bin"

echo "built $OUT.bin ($(stat -c%s "$OUT.bin") bytes, 16384 max)"
"$SIZE" "$OUT.elf" 2>/dev/null || true
