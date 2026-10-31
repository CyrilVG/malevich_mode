# malevich_mode

## Русский

**malevich_mode** — адаптация [Klipper](https://github.com/Klipper3d/klipper) для платы на STM32F407 с заводским USB-UART FT232R. Репозиторий содержит минимальные патчи к оригинальным исходникам, инструкцию сборки и автоматизированную проверку.

### Проверенная конфигурация платы

| Узел | Значение |
|---|---|
| MCU | STM32F407xx, Cortex-M4, 168 МГц |
| SWD Device ID | `0x413`, revision `0x1007` |
| Flash | 512 КиБ (проверено OpenOCD) |
| Корпус | LQFP100 |
| HSE | Кварц 25 МГц (маркировка подтверждена) |
| UART | UART5, **PC12 TX** / **PD2 RX**, AF8 |
| FT232R | Подключён к UART5, скорость 250000 бод |
| SWD | PA13 SWDIO, PA14 SWCLK, GND |
| Адрес прошивки | `0x08000000` (без пользовательского загрузчика) |
| Программатор | DAPLink / CMSIS-DAP или ST-Link |

**Особенность питания:** USB-разъём обслуживает FT232R, **но не питает саму плату STM32**. Появление `/dev/ttyUSB0` не означает, что микроконтроллер включён. Для работы требуется **отдельно подать штатное питание платы**. Это было проверено на реальном оборудовании: после подачи внешнего питания MCU успешно установил связь с Klipper.

USB-UART линии подключены следующим образом: PC12 (ножка LQFP100 №80) → RX FT232R; PD2 (ножка №54) ← TX FT232R. Не занимайте эти выводы одновременно под SDIO.

### Применение патчей

Используется официальный Klipper на закреплённом upstream-коммите `ee2c6fb6b00b2b5d097ef70d0868df7d74943b51`. При переходе на более новую версию требуется повторно проверить совместимость патчей.

```bash
git clone git@github.com:CyrilVG/malevich_mode.git ~/malevich_mode
cd ~/klipper
git status --short
for patch in ~/malevich_mode/patches/*.patch; do
    git apply --check "$patch" || exit 1
    git apply "$patch" || exit 1
done
make menuconfig
```

Для MCU в `make menuconfig` выберите:
- **Enable extra low-level configuration options:** Yes
- **Micro-controller Architecture:** STMicroelectronics STM32
- **Processor model:** STM32F407
- **Bootloader offset:** No bootloader
- **Clock Reference:** 25 MHz crystal
- **Communication interface:** Serial (on UART5 PD2/PC12)
- **Baud rate:** 250000

Сборка:

```bash
cd ~/klipper
make olddefconfig
make clean
make -j"$(nproc)"
ls -lh out/klipper.bin
```

### Как прошить плату (SWD)

**[Открыть руководство по прошивке](docs/flashing/README.md)** — общая схема подключения, требования к питанию, проверка BIN и устранение ошибок.

| Способ | Пошаговая инструкция |
|---|---|
| ST-Link V2/V3 | [ST-Link](docs/flashing/st-link.md) |
| DAPLink / CMSIS-DAP | [DAPLink](docs/flashing/cmsis-dap.md) — **проверен на этой плате** |
| Flipper Zero с DAP Link | [Flipper Zero](docs/flashing/flipper-zero.md) |
| Raspberry Pi напрямую через GPIO | [Raspberry Pi GPIO](docs/flashing/raspberry-pi-gpio.md) |

**Важно:** основная плата STM32 требует отдельного питания; FT232R по USB его не обеспечивает. Для записи используется SWD (PA13/PA14). Снятие RDP Level 1 стирает пользовательскую Flash. Используйте готовый BIN из [Releases](https://github.com/CyrilVG/malevich_mode/releases) с проверкой SHA-256.


### Klipper на Raspberry Pi

Определите постоянный путь адаптера:

```bash
ls -l /dev/serial/by-id/
```

Для проверенного экземпляра в `printer.cfg`:

```ini
[mcu board]
serial: /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A9WERABX-if00-port0
baud: 250000
```

Путь следует сверить с фактическим FT232R на хосте. Подайте отдельное питание основной плате, затем:

```bash
sudo systemctl restart klipper
tail -n 80 ~/printer_data/logs/klippy.log
```

После подачи отдельного питания Mainsail успешно распознаёт `stm32f407xx` с частотой **168 MHz**. Имя секции `[mcu board]` является примером; при использовании другого имени обновите соответствующие ссылки в `printer.cfg`.

### Готовые прошивки

Файлы доступны в разделе [Releases](https://github.com/CyrilVG/malevich_mode/releases):

- `malevich_mode-stm32f407-vX.Y.Z.bin` — прошивка для записи по SWD с адреса `0x08000000`;
- `malevich_mode-stm32f407-vX.Y.Z.zip` — архив с `klipper.bin`, `klipper.dict` и параметрами сборки;
- `SHA256SUMS.txt` и `MD5SUMS.txt` — контрольные суммы обоих файлов.

В Windows PowerShell можно проверить полученный бинарный файл:

```powershell
Get-FileHash .\malevich_mode-stm32f407-v0.1.0.bin -Algorithm SHA256
Get-FileHash .\malevich_mode-stm32f407-v0.1.0.bin -Algorithm MD5
```

Сверьте значения с соответствующими файлами сумм. В Linux:

```bash
sha256sum -c SHA256SUMS.txt
md5sum -c MD5SUMS.txt
unzip -t malevich_mode-stm32f407-v0.1.0.zip
```

Для проверки целостности рекомендуется SHA-256; MD5 опубликован дополнительно для совместимости.

### CI и прошивка

GitHub Actions применяет патчи к закреплённому Klipper, выполняет конфигурацию STM32F407 + UART5, собирает прошивку и публикует проверенные сборки в GitHub Actions, а версии — в разделе Releases.

Компиляция не заменяет аппаратную проверку новой сборки. Код исходного Klipper распространяется по GPLv3; данный репозиторий хранит только патчи, инструкции и проверки.

## English

**malevich_mode** adapts [Klipper](https://github.com/Klipper3d/klipper) to a custom STM32F407 board with an on-board FT232R USB-to-serial adapter. This repository contains minimal patches to upstream Klipper, build instructions, and CI validation.

### Verified hardware configuration

| Component | Specification |
|---|---|
| MCU | STM32F407xx, Cortex-M4, 168 MHz |
| SWD device ID | `0x413`, revision `0x1007` |
| Flash | 512 KiB, verified with OpenOCD |
| Package | LQFP100 |
| HSE | 25 MHz crystal, confirmed by component marking |
| UART | UART5, PC12 TX / PD2 RX, AF8 |
| FT232R | Connected to UART5, 250000 baud |
| SWD | PA13 SWDIO, PA14 SWCLK, GND |
| Firmware start address | `0x08000000` (no custom bootloader) |
| Flashing adapter | DAPLink / CMSIS-DAP or ST-Link |

**Power requirement:** USB powers the FT232R, **not the STM32 board**. Seeing `/dev/ttyUSB0` does not mean the MCU is powered. Apply the board's separate, specified power supply before connecting Klipper. This power topology has been confirmed on hardware.

The STM32 signals are routed as PC12 (LQFP100 pin 80) → FT232R RX and PD2 (pin 54) ← FT232R TX. Do not use PC12/PD2 for SDIO at the same time.

### Applying the patches

The supported upstream Klipper revision is pinned to `ee2c6fb6b00b2b5d097ef70d0868df7d74943b51`. Verify and adapt the patches before upgrading upstream.

```bash
git clone git@github.com:CyrilVG/malevich_mode.git ~/malevich_mode
cd ~/klipper
git status --short
for patch in ~/malevich_mode/patches/*.patch; do
    git apply --check "$patch" || exit 1
    git apply "$patch" || exit 1
done
make menuconfig
```

Use these `make menuconfig` settings:
- Enable extra low-level configuration options: **Yes**
- Micro-controller Architecture: **STMicroelectronics STM32**
- Processor model: **STM32F407**
- Bootloader offset: **No bootloader**
- Clock Reference: **25 MHz crystal**
- Communication interface: **Serial (on UART5 PD2/PC12)**
- Baud rate: **250000**

Build the firmware:

```bash
cd ~/klipper
make olddefconfig
make clean
make -j"$(nproc)"
ls -lh out/klipper.bin
```

### Flashing the board (SWD)

**[Open the flashing guide](docs/flashing/README.md)** for target pinout, separate power requirements, BIN verification and troubleshooting.

| Method | Step-by-step instructions |
|---|---|
| ST-Link V2/V3 | [ST-Link](docs/flashing/st-link.md) |
| DAPLink / CMSIS-DAP | [DAPLink](docs/flashing/cmsis-dap.md) — **verified on this board** |
| Flipper Zero with DAP Link | [Flipper Zero](docs/flashing/flipper-zero.md) |
| Direct Raspberry Pi GPIO SWD | [Raspberry Pi GPIO](docs/flashing/raspberry-pi-gpio.md) |

**Important:** the STM32 board needs separate power; FT232R USB does not power it. Firmware is written through SWD (PA13/PA14). Lowering RDP from Level 1 erases existing user Flash. Use the [Releases](https://github.com/CyrilVG/malevich_mode/releases) BIN and verify SHA-256 before flashing.


### Connecting Klipper on Raspberry Pi

Find the adapter's stable device path:

```bash
ls -l /dev/serial/by-id/
```

An example `printer.cfg` for the validated FT232R:

```ini
[mcu board]
serial: /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A9WERABX-if00-port0
baud: 250000
```

Check that this path matches your own hardware. Apply external power, then:

```bash
sudo systemctl restart klipper
tail -n 80 ~/printer_data/logs/klippy.log
```

Mainsail successfully identified the powered STM32F407 board at 168 MHz. The `[mcu board]` section name is an example; update other references in `printer.cfg` if using another name.

### Downloadable firmware

Versioned binaries are available from [Releases](https://github.com/CyrilVG/malevich_mode/releases):

- `malevich_mode-stm32f407-vX.Y.Z.bin` — raw binary to flash at `0x08000000`;
- `malevich_mode-stm32f407-vX.Y.Z.zip` — `klipper.bin`, `klipper.dict`, and build information;
- `SHA256SUMS.txt` and `MD5SUMS.txt` — checksums for both downloads.

To verify the downloaded binary in Windows PowerShell:

```powershell
Get-FileHash .\malevich_mode-stm32f407-v0.1.0.bin -Algorithm SHA256
Get-FileHash .\malevich_mode-stm32f407-v0.1.0.bin -Algorithm MD5
```

Compare the resulting hashes with the corresponding checksum files. On Linux:

```bash
sha256sum -c SHA256SUMS.txt
md5sum -c MD5SUMS.txt
unzip -t malevich_mode-stm32f407-v0.1.0.zip
```

Use SHA-256 as the primary integrity check; MD5 is provided for compatibility.

### CI and licensing

GitHub Actions applies patches to pinned Klipper sources, builds STM32F407 + UART5 firmware, checks the outputs, and publishes CI artifacts and versioned Releases.

A passing build is not a substitute for testing the new binary on hardware. Upstream Klipper is licensed under GPLv3; this repository contains patches, documentation, and checks rather than a full upstream copy.
