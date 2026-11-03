# PICASO panel MCU prototype

## Установка и проверка

Это экспериментальная прошивка с переносом энкодера и управления дисплеем
на STM32. Сборка и программные тесты выполнены; на вашей плате ещё не проверена.
Обязательно использовать новый BIN вместе с драйвером хоста из этого комплекта.

1. Сохраните рабочий printer.cfg и старый BIN для возврата.
2. Распакуйте комплект так, чтобы папка panel лежала в /home/pi/panel.
3. Остановите Klipper: `sudo systemctl stop klipper`.
4. Установите драйвер: `python3 ~/panel/install.py`.
5. Полностью замените старую секцию [display] содержимым display.cfg.
   Секции пользовательского меню оставьте. Старые параметры hc165_*, spi_*,
   encoder_pins, click_pin, cs_pin, dc_pin и reset_pin в [display] удалите.
6. Запишите новый BIN через SWD с адреса 0x08000000 прежним способом.
7. Запустите `sudo systemctl start klipper`.

Проверка: медленно и быстро повернуть в обе стороны, нажать и удержать кнопку,
выполнить HC_PANEL_STATUS. overflow должен оставаться 0. invalid показывает
недопустимые скачки сигналов A/B; max_scan_ticks — максимальный промежуток
между опросами в тактах MCU (CLOCK_FREQ находится в klipper.dict).

Затем остановите сервис Klipper: заставка должна появиться примерно через
секунду. После запуска сервиса меню вернётся, когда связь восстановлена и
картинка уже показана минимум 5 секунд. Это 5 секунд ОТ ПОЯВЛЕНИЯ картинки,
а не дополнительные 5 секунд после восстановления связи. Проверьте также
включение основной платы без Raspberry. Moonraker и браузер здесь не участвуют.

Если направление не подходит: panel_reverse_encoder: True. Шагов на щелчок
сейчас 2; параметр encoder_steps_per_detent допускает также 4.

Для отката: остановить Klipper, вернуть display.py из папки malevich-backup-*
(путь напечатает установщик), старую секцию [display] и прежний BIN, затем
запустить Klipper. Реле, бипер и USB этим изменением не настраиваются.

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

## Install on Raspberry Pi

Back up printer.cfg and keep the previous working BIN for rollback.
Extract the host/source ZIP so this folder is ~/panel. Then:

```sh
sudo systemctl stop klipper
python3 ~/panel/install.py
```

Replace the ENTIRE old [display] section with display.cfg, retaining any
custom [menu ...] sections. Remove old hc165_enable/hc165_poll_interval,
encoder_pins/click_pin, spi_*, cs_pin/dc_pin/reset_pin from that section.
The new firmware owns those fixed pins. Do not add duplicate sections.
Existing uc1701.py experimental changes are unused by lcd_type: malevich_panel.
The installer backs up display.py and any previously installed new driver.

Flash the matching new .bin over SWD to 0x08000000 using the existing board
procedure, with main board power present. Then:

```sh
sudo systemctl start klipper
```

Set panel_reverse_encoder: True if navigation direction needs reversing.
Use encoder_steps_per_detent: 2 (currently tested on the physical encoder);
4 is also supported. HC_PANEL_STATUS shows raw input, online/menu state,
queue overflow, invalid quadrature changes, longest scan interval in MCU ticks.
The timing measurement uses Klipper CLOCK_FREQ from klipper.dict.
Counters are cumulative since MCU reset. Overflow must stay zero.

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
