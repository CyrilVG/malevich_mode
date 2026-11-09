#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
common=(-mcpu=cortex-m4 -mthumb -mfloat-abi=soft -ffreestanding -fno-builtin -fdata-sections -ffunction-sections -Wall -Wextra -Werror -nostdlib)
if command -v arm-none-eabi-gcc >/dev/null 2>&1; then
  arm-none-eabi-gcc "${common[@]}" -Os -Wl,--gc-sections -T autodetect_linker.ld autodetect.c -o autodetect.elf
  arm-none-eabi-objcopy -O binary autodetect.elf autodetect.bin
else
  clang --target=arm-none-eabi "${common[@]}" -Oz -fuse-ld=lld \
    -Wl,-T,autodetect_linker.ld -Wl,--gc-sections autodetect.c -o autodetect.elf
  llvm-objcopy -O binary autodetect.elf autodetect.bin
fi
sha256sum autodetect.bin > autodetect.bin.sha256
