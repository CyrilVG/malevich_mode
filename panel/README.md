# PICASO panel MCU prototype

## Основной способ установки

Однокомандный установщик сам размещает полный комплект в `/home/pi/panel`,
подключает host-драйвер к Klipper и добавляет в `printer.cfg` секцию `[display]`
из `display.cfg`. Отдельно запускать `install.py` и копировать эту секцию не
нужно. Инструкции по ручной прошивке программатором находятся в
[`docs/flashing/README.md`](../docs/flashing/README.md).

## Установка и проверка

Используйте основной установщик из корня репозитория. Он устанавливает полный
исходный и host-пакет в `~/panel`, подключает драйвер к Klipper, прошивает
совместимый MCU BIN и записывает в конфиг ровно эту секцию:

```ini
[display]
lcd_type: malevich_panel
encoder_steps_per_detent: 4
panel_reverse_encoder: False
contrast: 239
invert: False
```

Старые ручные шаги с `python3 ~/panel/install.py` больше не нужны. Порядок
ручной прошивки программатором описан в
[`docs/flashing/README.md`](../docs/flashing/README.md).

После установки проверьте поворот энкодера в обе стороны, нажатие кнопки и
команду `HC_PANEL_STATUS`; `overflow` должен оставаться равным 0. `invalid`
считает недопустимые скачки сигналов A/B, а `max_scan_ticks` показывает
максимальный промежуток между опросами в тактах MCU. Klipper `CLOCK_FREQ`
находится в `klipper.dict`.

При остановке Klipper заставка появляется примерно через секунду. Меню
возвращается после восстановления связи, если заставка уже отображалась не
менее пяти секунд. Связь с Moonraker, браузером и Wi-Fi на это не влияет.
Откатите установку скриптом `restore.py` из напечатанного каталога резервной
копии. Реле, бипер и USB этим этапом не настраиваются.

## Technical details

Based on malevich_mode c010a92f and upstream Klipper ee2c6fb6. Target:
STM32F407VE, 25 MHz HSE, 168 MHz core, UART5 PC12/PD2 250000,
512 KiB flash, no bootloader, SWD flash address 0x08000000.

This is a firmware + host-driver pair. Existing stock firmware and the old
host-only HC165 module are not compatible with this new display section.
The exact supplied 128x64 bitmap is embedded in flash. Firmware owns these
pins from boot; its RESERVE_PINS entry prevents their reuse by normal config:
PD5 CS, PD6 RESET, PD7 OLED D/C + HC165 /PL, PB3 clock (HC165 CP inverted),
PB5 MOSI, PB4 HC165 Q7. Encoder D0/D1, active-low button D2.

## Install

Run the one-command installer from the repository README. It places this full
source and host package in `~/panel`, adds the Klipper driver, and configures the
display automatically. Follow the flashing wiki linked above only when using a
separate programmer. The installer makes a recoverable backup before it changes
the host files or MCU firmware.

Set `panel_reverse_encoder: True` if navigation direction needs reversing.
`HC_PANEL_STATUS` shows raw input, online/menu state, queue overflow, invalid
quadrature changes, and longest scan interval in MCU ticks. Counters are
cumulative since MCU reset; overflow should stay zero.

## Behaviour

- 2 kHz MCU scan independent of serial round trips, bounce-resistant native
  Klipper half/full quadrature state tables. Button debounce 5 ms; hold 800 ms.
- 256 ordered events with timestamps and acknowledged delivery; query every
  20 ms, faster while draining a backlog. Menu logic remains in Klippy.
- OLED rendering, pin ownership, reset/init, frame storage and splash are MCU
  functions. Scan and OLED never interleave inside a byte. IRQ masking is
  restricted to a single OLED byte; no full-frame interrupt lockout.
- Boot without host: logo after panel initialization. Host missing for 1 s:
  logo. Host shutdown: logo. No dependence on Moonraker/browser/Wi-Fi state.
- Logo remains until valid host heartbeat + complete framebuffer + at least
  FIVE seconds after the full logo was drawn. If disconnected longer than
  five seconds it can return to menu immediately after recovery. This is a
  minimum five-second DISPLAY duration, not an extra five seconds on reconnect.
- No old input events replayed after loss of host. Input is ignored while the
  logo is displayed. A button held across reconnection does not generate a click.
- A dead/hung MCU or lost board/display power cannot draw any image. Klipper
  heater/motor shutdown semantics are not modified or bypassed by this feature.
- USB host, buzzer and relay are untouched. They are not required for this stage.

## Verification and limits

Automated native-C tests run the actual firmware module with GPIO/time stubs:
quadrature direction, bounce, half/full detents, short/long press, ACK retry,
FIFO bounds, timeout, minimum logo dwell and shutdown. CI also cross-compiles
STM32 firmware and checks protocol commands. These tests do not establish
physical timing, display polarity, optical output or interference with printing.
Before using for a print, test fast turns in both directions, press/hold,
Klipper service stop/start, power-on with Raspberry off, and a loaded MCU.
Check overflow=0 and timing diagnostics. This is a hardware-unverified prototype.

Rollback: stop Klipper, restore display.py from the installer backup, restore
old [display] config and old MCU BIN. Start Klipper. Do not mix protocol versions.
