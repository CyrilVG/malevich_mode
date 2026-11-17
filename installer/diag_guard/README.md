# Malevich DIAG Guard v0.2.0-rc1

Generic host-side DIAG guard for printers using the matching shared-DIAG board topology and TMC2209 drivers on X, Y and extruder. The active Klipper configuration supplies each printer’s `diag_pin`; this module uses Klipper’s configured X/Y endstop objects and has no board GPIO numbers or pin aliases hard-coded. On compatible boards DIAG/INDEX is shared by the non-Z drivers; Z is outside the guarded path.

The guard uses the configured X/Y virtual endstops, enables X/Y/E through Klipper, checks UART `CHOPCONF.TOFF`, rejects a DIAG line already active before movement, uses 100 µs × 8 sampling for X/Y, and rejects triggers before 0.50 mm. Z homing, Z drivers, currents, `SGTHRS`, macros and coordinates are unchanged.

Requirements: `[tmc2209 stepper_x]`, `[tmc2209 stepper_y]`, and `[tmc2209 extruder]`, with valid UART access; X/Y configured for TMC2209 sensorless homing with the correct per-printer `diag_pin`; Klipper `homing.py` matching all three fail-closed patch anchors. Pins must reflect the physical board wiring: on supported boards the non-Z DIAG/INDEX signals are shared, while Z is excluded from the guard. The guard does not infer or repair a wrong pin map.

Installation is integrated into `install.sh`: compatible active/profile configs receive the guard automatically; `--diag-guard off` skips adding it in this run (an existing user-installed Guard is left untouched); `--diag-guard on` requires compatibility. `--keep-config` is evaluated from its actual included Klipper configuration, so other matching printers can use the same algorithm.

This release changes only Klipper host Python/config files. It does not replace or modify the STM32 binary. The installed firmware remains Malevich Klipper v0.2.0 (the existing X/XL binary, SHA-256 `4704cc2d51ad55adbc388a45e8795644ef4992acdf39cbecdcf11c52bdf8fbb5`). No extra MCU commands are required.

The X/Y homing behavior is intentionally unchanged from the XL implementation. Hardware validation was reported for one Designer XL; the generic installer and other printers’ pin maps have not been hardware-validated. The module keeps `XL_DIAG_GUARD_STATUS` as a compatibility alias for `MALEVICH_DIAG_GUARD_STATUS`.
