# malevich_mode — Klipper / STM32F407 / UART5

Проект **malevich_mode** (ранее **picaso_jailbreak**) содержит патчи к [официальному Klipper](https://github.com/Klipper3d/klipper) для платы на STM32F407. Плата успешно запущена с UART5 через штатный USB-UART FT232R.

В сборке MCU дополнительно отображается фирменная подпись **` [malevich_mode_tg:@Cyril_VG]`**, причём штатный номер версии Klipper сохраняется.

## Подтверждённая аппаратная конфигурация

| Компонент | Конфигурация / проверка |
|---|---|
| MCU | STM32F407xx (Klipper), SWD Device ID `0x413`, ревизия `0x1007` |
| Корпус | LQFP100 |
| Flash | **512 KiB** — определено OpenOCD после снятия RDP |
| Частота ядра | **168 MHz** — видна в Mainsail |
| Внешний кварц | **25 MHz**, подтверждено маркировкой кварца на плате |
| FT232R RX | STM32 `PC12` (UART5_TX), ножка 80 |
| FT232R TX | STM32 `PD2` (UART5_RX), ножка 54 |
| UART | UART5, AF8, **250000 бод** |
| SWD | `PA13` (SWDIO), `PA14` (SWCLK), GND; питание отдельно |
| Программатор | **DAPLink (CMSIS-DAP)**, проверено с OpenOCD; ST-Link тоже подходит |
| Прошивка | No bootloader, начало Flash `0x08000000` |

**Особенность питания платы:** штатный USB-разъём обслуживает FT232R, но **не подаёт питание на основную плату STM32**. При подключении только USB адаптер появляется как `/dev/ttyUSB0`, однако MCU не запускается. Для работы **необходимо отдельно подать штатное питание платы**. Это подтверждено в реальной установке Klipper.

Заводская защита RDP Level 1 была снята (со стиранием старой Flash), далее Klipper прошит через SWD с успешной проверкой `Verified OK`. При наличии отдельного питания Mainsail успешно обнаружил `mcu picaso (stm32f407xx)` на 168 MHz.

## Патчи

1. [`patches/0001-klipper-stm32f407-uart5-pc12-pd2.patch`](patches/0001-klipper-stm32f407-uart5-pc12-pd2.patch) — добавляет в `src/stm32/Kconfig` пункт `Serial (on UART5 PD2/PC12)` (только STM32F407 при `LOW_LEVEL_OPTIONS=y`); настраивает PC12/PD2, AF8, UART5 и `UART5_IRQn` в `src/stm32/serial.c`.
2. [`patches/0002-klipper-malevich-version-tag.patch`](patches/0002-klipper-malevich-version-tag.patch) — добавляет к версии MCU суффикс ` [malevich_mode_tg:@Cyril_VG]` через штатный параметр `-e` программы `scripts/buildcommands.py` в `Makefile`. Исходный git-хеш, отметка dirty и информация о сборке остаются в версии.

Пример отображения после перепрошивки:

```text
mcu picaso (stm32f407xx)
Version: ee2c6fb-dirty-20261025_164829-runner [malevich_mode_tg:@Cyril_VG]
Freq: 168 MHz
```

Реальные git-хеш, время сборки и hostname могут отличаться. Суффикс появляется **только после сборки и прошивки нового `klipper.bin`**; изменение README или `printer.cfg` на уже прошитом MCU его не добавляет.

Патчи проверяются по закреплённому коммиту официального Klipper: **`ee2c6fb6b00b2b5d097ef70d0868df7d74943b51`** (21.10.2026). При обновлении upstream необходимо заново проверить применимость патчей и сборку.

## Применение на Raspberry Pi

```bash
git clone git@github.com:CyrilVG/malevich_mode.git ~/malevich_mode

cd ~/klipper
git status --short
git apply --check ~/malevich_mode/patches/0001-klipper-stm32f407-uart5-pc12-pd2.patch
git apply ~/malevich_mode/patches/0001-klipper-stm32f407-uart5-pc12-pd2.patch
git apply --check ~/malevich_mode/patches/0002-klipper-malevich-version-tag.patch
git apply ~/malevich_mode/patches/0002-klipper-malevich-version-tag.patch
make menuconfig
```

При выборе `make menuconfig` задайте:
- Enable extra low-level configuration options: **Yes**;
- Architecture: **STMicroelectronics STM32**; Processor: **STM32F407**;
- Bootloader offset: **No bootloader**;
- Clock Reference: **25 MHz crystal**;
- Communication interface: **Serial (on UART5 PD2/PC12)**; baud: **250000**.

Сборка и проверка встроенного тега:

```bash
make olddefconfig
make clean
make -j"$(nproc)"
python3 ~/malevich_mode/scripts/check-version-tag.py out/klipper.dict
ls -lh out/klipper.bin
```

Чтобы обновить уже существующий клон старого репозитория после переименования:

```bash
git -C ~/picaso_jailbreak remote set-url origin git@github.com:CyrilVG/malevich_mode.git
```

При этом локальная папка может остаться старой — при применении патчей используйте соответствующий путь.

## Прошивка через SWD

В Windows с OpenOCD xPack и DAPLink (прошивка должна быть скопирована в `C:\Klipper\klipper.bin`):

```powershell
$ocd = (Get-ChildItem "C:\OpenOCD" -Filter openocd.exe -Recurse -File | Select-Object -First 1).FullName
& $ocd -f interface/cmsis-dap.cfg -f target/stm32f4x.cfg -c 'adapter speed 100; program C:/Klipper/klipper.bin verify reset exit 0x08000000'
```

Прошивка по этому адресу не требует пользовательского загрузчика. Для ST-Link вместо `interface/cmsis-dap.cfg` применяется `interface/stlink.cfg`.

**Внимание:** если MCU защищён RDP Level 1, его снятие стирает старую Flash; RDP Level 2 необратим. У ранее проверенной платы RDP уже переведён в Level 0. Для последующих обновлений `make flash` через UART5/FT232R не заменяет SWD-программатор.

## Подключение Klipper

Проверить постоянное имя USB-UART:

```bash
ls -l /dev/serial/by-id/
```

В `printer.cfg` для проверенной платы:

```ini
[mcu picaso]
serial: /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A9WERABX-if00-port0
baud: 250000
```

Проверьте, что путь совпадает с фактическим устройством на Raspberry Pi, и **подайте питание на основную плату**. После этого `sudo systemctl restart klipper`. Выводы PC12/PD2 нельзя одновременно использовать для SDIO.

## CI / готовая прошивка

GitHub Actions при push и PR:
1. загружает закреплённый исходный Klipper;
2. применяет оба патча с `git apply --check`;
3. собирает STM32F407 / 25 MHz / UART5 / 250000;
4. читает `out/klipper.dict` и **проверяет точный суффикс версии**;
5. публикует `out/klipper.bin` и `out/klipper.dict` в артефакте `klipper-stm32f407-uart5-malevich`.

Сборка и проверка версии не заменяют тестирование нового бинарника на плате.

Код Klipper распространяется на условиях GPLv3. В этом репозитории хранятся патчи и документация, а не полная копия исходников.
