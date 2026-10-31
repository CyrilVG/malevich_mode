# DAPLink / CMSIS-DAP

## Русский

**Статус: проверено на реальной плате.** DAPLink с CMSIS-DAP FW 1.0 успешно определил STM32F407 (Device ID 0x413) и выполнил запись с результатом **Verified OK** при SWD 100 кГц.

### 1. Подключение

Отключите питание и соедините **SWDIO → PA13**, **SWCLK → PA14**, **GND → GND**. NRST необязателен. Если ваш пробник имеет вход VTref, используйте только напряжение уже питаемой цели 3,3 В как опорное — не подключайте к плате выход питания от пробника. После подключения подайте штатное отдельное питание на основную плату STM32.

### 2. Windows PowerShell

Скопируйте скачанный файл malevich_mode-stm32f407-vX.Y.Z.bin из [Releases](https://github.com/CyrilVG/malevich_mode/releases) в C:\\Klipper\\klipper.bin. Установите [OpenOCD](https://openocd.org/) или распакуйте xPack в C:\\OpenOCD.

~~~powershell
$ocd = (Get-ChildItem "C:\OpenOCD" -Filter openocd.exe -Recurse -File | Select-Object -First 1).FullName
& $ocd --version
Test-Path "C:\Klipper\klipper.bin"
& $ocd -f interface/cmsis-dap.cfg -f target/stm32f4x.cfg -c 'adapter speed 100; init; targets; shutdown'
& $ocd -f interface/cmsis-dap.cfg -f target/stm32f4x.cfg -c 'adapter speed 100; program C:/Klipper/klipper.bin verify reset exit 0x08000000'
~~~

Ожидаемые строки:

~~~text
Info : device id = 0x10076413
Info : flash size = 512 KiB
** Programming Finished **
** Verified OK **
** Resetting Target **
~~~

ID и размер Flash указаны как результаты **проверенного экземпляра**. Не требуйте точной версии FW CMSIS-DAP у других программаторов.

### 3. Linux

Установите OpenOCD, убедитесь, что CMSIS-DAP обнаруживается USB-хостом, и укажите полный путь к скачанному файлу:

~~~bash
sudo apt-get install openocd
sudo openocd -f interface/cmsis-dap.cfg -f target/stm32f4x.cfg \
  -c "adapter speed 100; program $HOME/klipper.bin verify reset exit 0x08000000"
~~~

Заранее скопируйте проверенный BIN в ~/klipper.bin. Используйте sudo только если для USB-пробника не настроены корректные права доступа.

**Не путайте DAPLink с FT232R:** FT232R используется для работы Klipper, а CMSIS-DAP — для SWD-программирования.

[← Все способы](README.md)

---

## English

**Verified on the actual board.** A DAPLink/CMSIS-DAP FW 1.0 probe identified the STM32F407 (device ID 0x413) and successfully flashed and verified its 512 KiB Flash at **100 kHz SWD**.

### 1. Wiring

Power off first. Connect **SWDIO → PA13**, **SWCLK → PA14**, **GND → GND**. NRST is optional. If the probe needs VTref, use the powered target's 3.3 V as a **reference input only**; never power this board from the debugger. Then supply the board's normal separate power.

### 2. Windows PowerShell

Put the downloaded BIN at C:\\Klipper\\klipper.bin and install [OpenOCD](https://openocd.org/) under C:\\OpenOCD:

~~~powershell
$ocd = (Get-ChildItem "C:\OpenOCD" -Filter openocd.exe -Recurse -File | Select-Object -First 1).FullName
& $ocd --version
Test-Path "C:\Klipper\klipper.bin"
& $ocd -f interface/cmsis-dap.cfg -f target/stm32f4x.cfg -c 'adapter speed 100; init; targets; shutdown'
& $ocd -f interface/cmsis-dap.cfg -f target/stm32f4x.cfg -c 'adapter speed 100; program C:/Klipper/klipper.bin verify reset exit 0x08000000'
~~~

Look for **Programming Finished**, **Verified OK**, and a target reset. These values reflect the validated board; a different CMSIS-DAP firmware version is not inherently an error.

### 3. Linux

Install OpenOCD and put the verified BIN at ~/klipper.bin:

~~~bash
sudo apt-get install openocd
sudo openocd -f interface/cmsis-dap.cfg -f target/stm32f4x.cfg \
  -c "adapter speed 100; program $HOME/klipper.bin verify reset exit 0x08000000"
~~~

USB permissions may require sudo unless udev rules are configured. FT232R is for Klipper UART communication, not the SWD programming link.

[← All flashing methods](README.md)
