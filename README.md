<h1 align="center">
  <img src="docs/assets/header.svg" alt="malevich_mode" width="960">
</h1>

<p align="center">
  <a href="https://boosty.to/cyril_vg/donate">
    <img src="docs/assets/boosty.svg" alt="Поддержать на Boosty / Support on Boosty" width="320" height="60">
  </a>
</p>

<p align="center">
  <a href="#русский">Русский</a> · <a href="#english">English</a> ·
  <a href="https://github.com/CyrilVG/malevich_mode/releases/latest">Скачать / Downloads</a> ·
  <a href="docs/flashing/README.md">Прошивка / Flashing</a>
</p>

<details>
<summary>⚠️ Важно / Important</summary>

**Русский:** Используйте прошивку и инструкции на свой страх и риск. Автор не несёт ответственности за повреждение оборудования и последствия установки.

**English:** Use the firmware and instructions at your own risk. The author is not responsible for equipment damage or consequences of installation.
</details>

---

## Русский

### Установка одной командой на Raspberry Pi

Установщик для Klipper на Raspberry Pi 3/4/5 сначала запускает AutoDetect v0.6.0, затем предлагает выбрать Designer X или XL с подсказкой найденной модели. Профили X и XL разделены; XL переключает банки драйверов через штатный `select_pins` Klipper. Для двух сопел скрипт спросит вариант и сохранит текущий конфиг, пока отдельный профиль не проверен.

```bash
bash <(wget -qO- https://raw.githubusercontent.com/CyrilVG/malevich_mode/main/install.sh)
```

Перед запуском SWD-соедините Raspberry Pi и STM32 по проверенной распиновке, оставьте VCC раздельным и отключите SPI0. Для Orange Pi 3 LTS/5/5 Plus GPIO и OpenOCD пока не подтверждены, поэтому установщик не выполняет прошивку. Распиновка, условия AutoDetect и параметры установки описаны в [инструкции установщика](installer/README.md).

Выбранный профиль раскладывает макросы в отдельный `macros.cfg`; перед записью сохраняются файлы и полный дамп flash. Используйте `--keep-config`, чтобы оставить активный конфиг, или `--check --printer-model X|XL`, чтобы проверить комплект без прошивки. USB Host/MSC для флешек через разъём LCD пока не реализован.

[Подробности, распиновка, параметры и откат](installer/README.md)

**malevich_mode** — адаптация [Klipper](https://github.com/Klipper3d/klipper) для платы на STM32F407 с заводским USB-UART FT232R. Репозиторий содержит установщик, прошивку и wiki с инструкциями по ручной прошивке.

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

### Ручная прошивка

Для прошивки v0.2.0 отдельным программатором скачайте BIN в разделе [Releases](https://github.com/CyrilVG/malevich_mode/releases). Подключение программаторов и порядок прошивки — в [wiki](docs/flashing/README.md).

### CI и прошивка

GitHub Actions собирает и проверяет прошивку STM32F407 + UART5. Готовые версии публикуются в разделе Releases. Проверка сборки не заменяет испытание новой версии на плате. Klipper распространяется по GPLv3.

## English

### One-command Raspberry Pi installation

The installer targets a clean Klipper setup on Raspberry Pi 3, 4 or 5 with the STM32F407VE board. It offers host-board and printer-model choices. 

```bash
bash <(wget -qO- https://raw.githubusercontent.com/CyrilVG/malevich_mode/main/install.sh)
```

For Raspberry Pi 3/4/5, connect with power off: **header pin 23 / GPIO11 → PA14/SWCLK, pin 24 / GPIO8 → PA13/SWDIO, pin 20 → GND**. Power the STM32 board separately, leave VCC disconnected, and disable SPI0. Select Designer X or XL: X installs its firmware and configuration profile; XL stops safely until its validated bundle is published. Orange Pi 3 LTS, Orange Pi 5 and 5 Plus appear as future menu options, but are not flashed until their GPIO/SWD maps are verified.

The X profile replaces `printer.cfg` and `board_pins.cfg`; host files and the full flash are backed up first. Add `--keep-config` to preserve the existing configuration, or `--check` to review the plan without changes.

[Details, pinout, options and rollback](installer/README.md).

**malevich_mode** adapts [Klipper](https://github.com/Klipper3d/klipper) to a custom STM32F407 board with an on-board FT232R USB-to-serial adapter. This repository provides the installer, firmware, and a wiki for manual flashing.

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

### Manual flashing

For programming v0.2.0 with a separate adapter, download the BIN from [Releases](https://github.com/CyrilVG/malevich_mode/releases). Adapter wiring and flashing steps are in the [wiki](docs/flashing/README.md).

### CI and licensing

GitHub Actions builds and checks STM32F407 + UART5 firmware. Versioned downloads are published under Releases. A passing build does not replace testing each new version on hardware. Klipper is licensed under GPLv3.
