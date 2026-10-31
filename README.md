# malevich_mode

**malevich_mode** — адаптация [Klipper](https://github.com/Klipper3d/klipper) для платы на STM32F407 с заводским USB-UART FT232R. Репозиторий содержит минимальные патчи к оригинальным исходникам, инструкцию сборки и автоматизированную проверку.

## Проверенная конфигурация платы

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

## Применение патчей

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

## Запись через SWD (Windows / DAPLink)

На Windows должен быть установлен OpenOCD. Плата должна иметь отдельное питание, а линии SWD — общий GND, PA13/SWDIO и PA14/SWCLK. После копирования `klipper.bin` в `C:\Klipper\klipper.bin` выполните в PowerShell:

```powershell
$ocd = (Get-ChildItem "C:\OpenOCD" -Filter openocd.exe -Recurse -File | Select-Object -First 1).FullName
& $ocd -f interface/cmsis-dap.cfg -f target/stm32f4x.cfg -c 'adapter speed 100; program C:/Klipper/klipper.bin verify reset exit 0x08000000'
```

Если применяется ST-Link, замените `interface/cmsis-dap.cfg` на `interface/stlink.cfg`.

**Осторожно с RDP:** снятие защиты Level 1 вызывает стирание пользовательской Flash. Для проверенной платы переход RDP Level 1 → Level 0 уже был выполнен; команда выше не выполняет разблокировку повторно. Встроенный загрузчик STM32 не использует UART5/FT232R для стандартного обновления — SWD оставьте доступным.

## Klipper на Raspberry Pi

Определите постоянный путь адаптера:

```bash
ls -l /dev/serial/by-id/
```

Для проверенного экземпляра в `printer.cfg`:

```ini
[mcu picaso]
serial: /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A9WERABX-if00-port0
baud: 250000
```

Путь следует сверить с фактическим FT232R на хосте. Подайте отдельное питание основной плате, затем:

```bash
sudo systemctl restart klipper
tail -n 80 ~/printer_data/logs/klippy.log
```

Успешное соединение подтверждено в Mainsail как `mcu picaso (stm32f407xx)`, **168 MHz**.

## Готовые прошивки

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

## CI и прошивка

GitHub Actions применяет патчи к закреплённому Klipper, выполняет конфигурацию STM32F407 + UART5, собирает прошивку и публикует проверенные сборки в GitHub Actions, а версии — в разделе Releases.

Компиляция не заменяет аппаратную проверку новой сборки. Код исходного Klipper распространяется по GPLv3; данный репозиторий хранит только патчи, инструкции и проверки.
