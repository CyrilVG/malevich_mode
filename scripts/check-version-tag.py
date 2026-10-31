#!/usr/bin/env python3
"""Verify that a built Klipper MCU data dictionary carries the branding tag."""
import json
import pathlib
import sys

EXPECTED_SUFFIX = " [malevich_mode_tg:@Cyril_VG]"


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: check-version-tag.py path/to/klipper.dict")
    dictionary = json.loads(pathlib.Path(sys.argv[1]).read_text())
    version = dictionary["version"]
    print("MCU firmware version:", version)
    if not version.endswith(EXPECTED_SUFFIX):
        raise SystemExit("ERROR: MCU version does not end with " + repr(EXPECTED_SUFFIX))
    if len(version) <= len(EXPECTED_SUFFIX):
        raise SystemExit("ERROR: original Klipper version missing")
    print("OK: Klipper version preserved; malevich_mode suffix found")


if __name__ == "__main__":
    main()
