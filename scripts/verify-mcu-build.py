#!/usr/bin/env python3
"""Validate metadata in a compiled Klipper MCU dictionary."""
import json
import pathlib
import sys

EXPECTED_SUFFIX = " [malevich_mode_tg:@Cyril_VG]"


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: verify-mcu-build.py path/to/klipper.dict")
    dictionary = json.loads(pathlib.Path(sys.argv[1]).read_text())
    version = dictionary["version"]
    print("MCU firmware version:", version)
    if not version.endswith(EXPECTED_SUFFIX):
        raise SystemExit("ERROR: MCU version does not end with " + repr(EXPECTED_SUFFIX))
    if len(version) <= len(EXPECTED_SUFFIX):
        raise SystemExit("ERROR: original Klipper version missing")
    print("OK: MCU build metadata validated")


if __name__ == "__main__":
    main()
