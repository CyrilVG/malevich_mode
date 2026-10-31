# Flipper Zero (DAP Link)

## Русский

**Статус:** Flipper Zero может работать как CMSIS-DAP SWD-программатор с приложением **DAP Link**; это подтверждено документацией разработчика Flipper, **но именно на нашей STM32F407-плате этот вариант пока не испытан**. Flipper используется как мост **USB → CMSIS-DAP → SWD**, поэтому для записи также нужен ПК с OpenOCD.

### 1. Подготовка Flipper

1. Установите официальное приложение [DAP Link из Flipper Lab](https://lab.flipper.net/apps/dap_link) (раздел GPIO), при необходимости обновите прошивку Flipper и вставьте карту microSD.
2. На Flipper откройте **Apps → GPIO → DAP Link** и запустите его.
3. Откройте меню приложения **Config → Help and Pinout** и **сверьте актуальные GPIO**. Обычно: Flipper **pin 10 → SWCLK**, **pin 12 → SWDIO**, **pin 11 → GND**. Конфигурация приложения может быть изменена пользователем.
4. При выключенном питании соедините линии с STM32: SWCLK → PA14, SWDIO → PA13, GND → GND. Подайте отдельное штатное питание платы.
5. Подключите Flipper USB-кабелем к компьютеру. В ОС должен появиться CMSIS-DAP адаптер.

**Внимание:** Flipper pin 9 (3V3) **не соединяйте как источник питания** с основной платой. Питание STM32 по USB Flipper не предусмотрено; возможна обратная подпитка.

### 2. Прошивка через Windows PowerShell

Установите OpenOCD и поместите скачанный BIN в C:\\Klipper\\klipper.bin.

~~~powershell
$ocd = (Get-ChildItem "C:\OpenOCD" -Filter openocd.exe -Recurse -File | Select-Object -First 1).FullName
& $ocd -f interface/cmsis-dap.cfg -f target/stm32f4x.cfg -c 'adapter speed 100; init; targets; shutdown'
& $ocd -f interface/cmsis-dap.cfg -f target/stm32f4x.cfg -c 'adapter speed 100; program C:/Klipper/klipper.bin verify reset exit 0x08000000'
~~~

Это **те же команды, что для DAPLink**, потому что приложение предоставляет USB CMSIS-DAP. На Windows может потребоваться корректный USB-драйвер выбранного интерфейса Flipper; проверяйте устройство в Диспетчере устройств. Не переназначайте драйвер на FT232R.

### 3. Проверка

Успех — **Verified OK**; после перезапуска и при внешнем питании STM32 должен появиться в Klipper. Если OpenOCD не находит адаптер, проверьте, запущено ли приложение DAP Link, USB-кабель передачи данных и список USB-устройств; если не находит MCU — SWD-провода и питание.

Источники: [Flipper Developer Docs: DAP LINK as SWD probe](https://developer.flipper.net/flipperzero/doxygen/app_dev_debugging_faps.html), [Flipper GPIO pinout](https://docs.flipper.net/zero/gpio-and-modules), [DAP Link (Flipper Lab)](https://lab.flipper.net/apps/dap_link).

[← Все способы](README.md)

---

## English

**Status:** Flipper Zero supports a CMSIS-DAP SWD probe mode through the **DAP Link** app, according to Flipper developer documentation. It **has not yet been tested on this exact STM32F407 target**. The setup needs a USB-connected computer with OpenOCD: Flipper acts as the **USB/CMSIS-DAP to SWD bridge**.

### 1. Prepare the Flipper

1. Install [DAP Link from Flipper Lab](https://lab.flipper.net/apps/dap_link) (GPIO category).
2. Launch **Apps → GPIO → DAP Link**.
3. Open **Config → Help and Pinout** to confirm current app settings. Common pin mapping: Flipper **pin 10 SWCLK**, **pin 12 SWDIO**, **pin 11 GND**.
4. With power disconnected, connect SWCLK to STM32 PA14, SWDIO to PA13, and GND to GND.
5. Apply the board's independent power supply; connect Flipper to the PC using a data-capable USB cable.

**Never power this board through Flipper GPIO pin 9 (3V3)**; doing so can backfeed or damage hardware.

### 2. Flash from Windows

Install OpenOCD; copy the release BIN to C:\\Klipper\\klipper.bin:

~~~powershell
$ocd = (Get-ChildItem "C:\OpenOCD" -Filter openocd.exe -Recurse -File | Select-Object -First 1).FullName
& $ocd -f interface/cmsis-dap.cfg -f target/stm32f4x.cfg -c 'adapter speed 100; init; targets; shutdown'
& $ocd -f interface/cmsis-dap.cfg -f target/stm32f4x.cfg -c 'adapter speed 100; program C:/Klipper/klipper.bin verify reset exit 0x08000000'
~~~

These are the **same commands as DAPLink**, because Flipper exposes CMSIS-DAP over USB. If the probe is not detected, verify the app is running, your USB cable and CMSIS-DAP interface driver. Do not alter the separate FT232R serial driver's configuration.

### 3. Confirm

Look for **Verified OK**. The STM32 still needs its separate power supply when running Klipper.

References: [Flipper Developer Docs](https://developer.flipper.net/flipperzero/doxygen/app_dev_debugging_faps.html), [Flipper GPIO pinout](https://docs.flipper.net/zero/gpio-and-modules), [Flipper Lab DAP Link](https://lab.flipper.net/apps/dap_link).

[← All flashing methods](README.md)
