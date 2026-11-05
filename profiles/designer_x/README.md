# Designer X profile

`printer.cfg` and `board_pins.cfg` are the supplied Designer X configuration and
pin map. The installer replaces `@MCU_SERIAL@` with the detected FT232R path,
uses the configured printer-data `gcodes` directory, and sets the Malevich panel
driver options. The active files are backed up before installation.

The profile is intended for the Designer X board with TMC2130 drivers. Check
axis direction, endstops, sensor readings, heater outputs, relay polarity and
thermal protections on the actual machine before printing.
