# picaso_jailbreak — Klipper / STM32F407 / UART5

Патч к [официальному Klipper](https://github.com/Klipper3d/klipper), добавляющий UART5 на **PC12 (TX) / PD2 (RX)** в `make menuconfig` для STM32F407.

## Аппаратная конфигурация

| Устройство | Сигнал |
|---|---|
| STM32F407 (LQFP100) | 168 MHz, SWD PA13/PA14 |
| FT232R RX | STM32 **PC12 / UART5_TX**, вывод корпуса 80 |
| FT232R TX | STM32 **PD2 / UART5_RX**, вывод корпуса 54 |
| Соединение хоста | FT232R → USB Raspberry Pi (`/dev/ttyUSB0` или `/dev/serial/by-id/...`) |
| Прошивка | ST-Link V2/V2+ → SWD |
| Уровни UART | 3,3 В |
| Bootloader offset | No bootloader, адрес `0x08000000` |

**Важно:** 25 MHz HSE выбран на основании ранее сохранённого `.config`, но его необходимо проверить на аппаратной плате до прошивки. `Device ID 0x413` сам по себе не уточняет артикул F405/F407/F415/F417. Параметр `CONFIG_FLASH_SIZE=0x80000` — стандартное значение сборки Klipper, а не подтверждённая ёмкость Flash данного экземпляра.

## Состав изменений

Патч [`patches/0001-klipper-stm32f407-uart5-pc12-pd2.patch`](patches/0001-klipper-stm32f407-uart5-pc12-pd2.patch):
- добавляет `STM32_SERIAL_UART5_PC12_PD2` в `src/stm32/Kconfig` (только STM32F407, при `LOW_LEVEL_OPTIONS=y`);
- задаёт `GPIO_AF_MODE 8`, `GPIO_Tx PC12`, `GPIO_Rx PD2`, `UART5` и `UART5_IRQn` в `src/stm32/serial.c`;
- использует штатный драйвер serial Klipper без альтернативного загрузчика и без изменения других UART.

Проверяемая версия upstream: **Klipper `ee2c6fb6b00b2b5d097ef70d0868df7d74943b51` (2026-10-21)**. При обновлении Klipper патч требуется проверять повторно.

## Как применить к установленному Klipper на Raspberry Pi

```bash
# Загрузить этот репозиторий (для приватного репозитория потребуется доступ GitHub)
git clone git@github.com:CyrilVG/picaso_jailbreak.git ~/picaso_jailbreak

cd ~/klipper
git status --short                  # убедиться, что нет конфликтующих локальных изменений
git apply --check ~/picaso_jailbreak/patches/0001-klipper-stm32f407-uart5-pc12-pd2.patch
git apply ~/picaso_jailbreak/patches/0001-klipper-stm32f407-uart5-pc12-pd2.patch
make menuconfig
```

В `make menuconfig` выбери:
1. **Enable extra low-level configuration options**: Yes;
2. **Micro-controller Architecture**: STMicroelectronics STM32;
3. **Processor model**: STM32F407;
4. **Bootloader offset**: No bootloader;
5. **Clock Reference**: 25 MHz crystal *(только если кварц действительно 25 MHz)*;
6. **Communication interface**: **Serial (on UART5 PD2/PC12)**;
7. **Baud rate**: 250000.

Далее:

```bash
make olddefconfig
grep -E 'CONFIG_MACH_STM32F407=|CONFIG_STM32_SERIAL_UART5_PC12_PD2=|CONFIG_SERIAL_BAUD=|CONFIG_CLOCK_REF_FREQ=' .config
make clean
make -j"$(nproc)"
ls -lh out/klipper.bin
```

## Прошивка и восстановление через SWD

ST-Link: SWDIO ↔ PA13, SWCLK ↔ PA14, GND ↔ GND. Плата должна получать корректное питание, напряжение сигналов 3,3 В. NRST полезен для восстановления.

Если RDP Level 1 активен, его снятие **безвозвратно стирает пользовательскую Flash**. Сначала проверь Option Bytes в STM32CubeProgrammer и не снимай защиту, если заводская прошивка ещё нужна. RDP Level 2 нельзя снять.

При отключённой защите и сохранённом исходном бинарнике можно прошить через STM32CubeProgrammer (ST-Link, адрес `0x08000000`) или OpenOCD:

```bash
cd ~/klipper
openocd -f interface/stlink.cfg -f target/stm32f4x.cfg \
  -c "program out/klipper.bin 0x08000000 verify reset exit"
```

Наличие Klipper на UART5 **не создаёт UART5-загрузчик**. Для последующих обновлений рекомендуем оставлять SWD подключаемым. Обычный `make flash` через USB FT232R, сидящий на UART5, не гарантирует обновление приложения.

## Использование в Klipper

Узнай постоянное имя адаптера:

```bash
ls -l /dev/serial/by-id/
```

В `printer.cfg` укажи **реальный** путь устройства:

```ini
[mcu]
serial: /dev/serial/by-id/usb-FTDI_...-if00-port0
baud: 250000
```

После сохранения `printer.cfg`: `sudo systemctl restart klipper`. Если соединение отсутствует, проверь физические линии TX/RX, HSE, питание и лог Klipper. PC12/PD2 также задействуются SDIO: параллельно пользоваться SDIO на этих выводах нельзя.

## Автоматическая проверка

GitHub Actions применяет патч к закреплённому upstream-коммиту, включает STM32F407 / HSE 25 MHz / UART5 / 250000 и пытается собрать `out/klipper.bin`. После успешной компиляции `klipper.bin` загружается как артефакт **klipper-stm32f407-uart5** на странице GitHub Actions. Успешная компиляция не заменяет аппаратный тест на плате.

Лицензия модифицируемого Klipper — GPLv3. Этот репозиторий хранит только патч и документацию, а не форк всего исходного дерева.
