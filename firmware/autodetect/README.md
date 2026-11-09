# AutoDetect v0.6.0

This is a temporary diagnostic image used by the installer to identify Designer X
(TMC2130 over SPI) or Designer XL (TMC2209 over two UART banks). The installer
flashes it through SWD, reads the result from the board's FT232R serial port, then
flashes the selected Klipper image. AutoDetect is not a printer firmware and must
not be left installed for normal printer use.

The image performs one passive line check and one active scan only after explicit
serial commands. It checks TMC identity registers, does not issue STEP/DIR
commands, and automatically releases PE14 after a maximum of 45 seconds. The
installer additionally requires confirmation that the motors and heaters are
physically disconnected and that PE14 measures about 3.3 V without abnormal
current or heating.

**Hardware checks are still required.** The active scan can toggle PE11/PE12/PE13;
on XL those lines may be STEP pins. Disconnect motors and heaters before the
scan. Do not connect or disconnect the board or driver modules while powered. If
AutoDetect reports `UNKNOWN`, the installer restores the flash backup and stops;
absence of a response is not treated as proof of either printer model.

The image uses UART5 PC12/PD2 to the FT232R at 115200 baud. The sources and static
checks in this directory are provided for review. The static test checks the
binary layout, pin setup, scan sequence, TMC response validation and SHA256; it
does not replace a physical test on X and XL boards.
