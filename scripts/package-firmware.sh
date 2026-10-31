#!/usr/bin/env bash
# Assemble versioned STM32F407 firmware downloads and verify integrity.
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "Usage: package-firmware.sh VERSION BUILD_DIR DIST_DIR" >&2
  exit 2
fi
VERSION="$1"
BUILD_DIR="$2"
DIST_DIR="$3"
if [[ ! "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Invalid release version: $VERSION" >&2
  exit 2
fi
test -s "$BUILD_DIR/klipper.bin"
test -s "$BUILD_DIR/klipper.dict"

mkdir -p "$DIST_DIR" "$DIST_DIR/staging"
BASE="malevich_mode-stm32f407-$VERSION"
cp "$BUILD_DIR/klipper.bin" "$DIST_DIR/$BASE.bin"
cp "$BUILD_DIR/klipper.bin" "$DIST_DIR/staging/klipper.bin"
cp "$BUILD_DIR/klipper.dict" "$DIST_DIR/staging/klipper.dict"

cat > "$DIST_DIR/staging/BUILDINFO.txt" <<EOF
Project: malevich_mode
Version: $VERSION
MCU: STM32F407
Flash start: 0x08000000
Flash size: 512 KiB
Clock: 168 MHz core, 25 MHz HSE
Serial: UART5 PC12/PD2, 250000 baud
Klipper upstream commit: ee2c6fb6b00b2b5d097ef70d0868df7d74943b51
EOF

(
  cd "$DIST_DIR/staging"
  zip -X -q -9 "../$BASE.zip" klipper.bin klipper.dict BUILDINFO.txt
)
(
  cd "$DIST_DIR"
  sha256sum "$BASE.bin" "$BASE.zip" > SHA256SUMS.txt
  md5sum "$BASE.bin" "$BASE.zip" > MD5SUMS.txt
  sha256sum -c SHA256SUMS.txt
  md5sum -c MD5SUMS.txt
  unzip -t -q "$BASE.zip"
  cmp "$BASE.bin" <(unzip -p "$BASE.zip" klipper.bin)
)
cat > "$DIST_DIR/RELEASE_NOTES.md" <<EOF
## malevich_mode $VERSION

STM32F407 firmware for the on-board FT232R serial interface (UART5, PC12 TX / PD2 RX, 250000 baud).

**Power:** USB power to the FT232R does not power the STM32 board; external power is required.

**Flashing:** Use SWD and write `$BASE.bin` at address `0x08000000`.

**Downloads:** A raw firmware binary, a ZIP archive (including firmware, MCU dictionary and build information), and SHA-256/MD5 checksum files.

Verify files with `sha256sum -c SHA256SUMS.txt` or `Get-FileHash -Algorithm SHA256` on Windows. MD5 is included for compatibility; prefer SHA-256.
EOF
echo "Release package ready: $BASE"
