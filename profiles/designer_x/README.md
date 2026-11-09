# Designer X profile

`printer.cfg`, `board_pins.cfg`, and `macros.cfg` are the supplied Designer X
configuration, pin map, and macro collection. The installer replaces
`@MCU_SERIAL@` with the detected FT232R path, uses the configured printer-data
`gcodes` directory, and sets the Malevich panel options. The active files are
backed up before installation.

The profile is intended for the Designer X board with TMC2130 drivers. Check
axis direction, endstops, sensor readings, heater outputs, relay polarity and
thermal protections on the actual machine before printing.

`USB_HOST_DM=PB14` and `USB_HOST_DP=PB15` identify the LCD USB connector wiring.
The pin aliases do not enable USB Host/MSC support; that needs a firmware USB
host stack and a file-transfer service to Moonraker's `gcodes` directory.
