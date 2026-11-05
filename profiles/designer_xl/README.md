# Designer XL profile status

The installer reserves these paths for a future XL bundle:

- `profiles/designer_xl/printer.cfg`
- `firmware/designer_xl/klipper.bin`

The current uploaded analysis describes XL hardware with TMC2209 UART banking.
It is not a safe install profile: the PC3 bank switching and the exact validated
firmware image still need to be resolved. The installer therefore recognizes
the XL selection but stops before changing printer files or MCU flash when the
matching bundle is absent.
