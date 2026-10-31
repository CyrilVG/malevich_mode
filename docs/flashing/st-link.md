# ST-Link (ST-LINK V2/V3)

## Русский

**Статус:** стандартный поддерживаемый SWD-программатор; на этом экземпляре платы пока не испытан отдельно. Принцип записи тот же, что и у проверенного CMSIS-DAP.

### 1. Подключение

При **выключенном питании** соедините ST-Link SWDIO → PA13, SWCLK → PA14, GND → GND. Если ST-Link требует VTref, подайте на его вход опорные **3,3 В уже питаемой платы**; не подключайте выход питания программатора к основной плате. При желании подключите NRST ↔ NRST. Затем отдельно включите питание STM32.

Не полагайтесь на цвет проводов и надписи 3V3 на клонах ST-Link: проверьте назначение конкретного разъёма.

### 2. Windows: OpenOCD (командный способ)

Установите [OpenOCD](https://openocd.org/) (либо используйте установленный xPack); скачайте проверенный BIN из [Releases](https://github.com/CyrilVG/malevich_mode/releases) и скопируйте его в C:\\Klipper\\klipper.bin.

~~~powershell
$ocd = (Get-ChildItem "C:\OpenOCD" -Filter openocd.exe -Recurse -File | Select-Object -First 1).FullName
Test-Path "C:\Klipper\klipper.bin"
& $ocd -f interface/stlink.cfg -f target/stm32f4x.cfg -c 'adapter speed 100; init; targets; shutdown'
& $ocd -f interface/stlink.cfg -f target/stm32f4x.cfg -c 'adapter speed 100; program C:/Klipper/klipper.bin verify reset exit 0x08000000'
~~~

Первый запуск **не записывает** Flash: он проверяет SWD. Второй записывает BIN, читает обратно для верификации и сбрасывает MCU. Ожидайте Programming Finished / Verified OK.

На Linux используйте openocd с теми же -f и -c, указав абсолютный путь к локальному BIN.

### 3. Windows: STM32CubeProgrammer (GUI)

Альтернатива OpenOCD — официальный [STM32CubeProgrammer](https://www.st.com/en/development-tools/stm32cubeprog.html):

1. Выберите **ST-LINK**, порт **SWD**, подключитесь к STM32F407.
2. Откройте **Erasing & Programming**, выберите скачанный .bin.
3. **Start address: 0x08000000**, включите **Verify programming**, выполните Download.
4. При успешной проверке выполните Reset/Disconnect и перезапустите плату, сохраняя отдельное питание.

**Не применяйте Full chip erase или RDP unlock без необходимости:** снятие RDP Level 1 уничтожает старую Flash. Не перепутайте адрес приложения с адресом загрузчика.

[← Все способы](README.md)

---

## English

**Status:** a supported, standard SWD adapter; this exact target has not yet been separately tested with ST-Link.

### 1. Wiring

With the target **powered off**, connect SWDIO → PA13, SWCLK → PA14 and GND → GND. Only if your adapter requires VTref, connect its **voltage-sense input** to the powered target's regulated 3.3 V rail. Do not power the target using the probe. Optional NRST → NRST. Apply the target's normal external power after wiring.

Verify the connector labels of your specific ST-Link model or clone; wire colors and "3V3" labels are not universally reliable.

### 2. Windows: OpenOCD

Install [OpenOCD](https://openocd.org/), place the release BIN at C:\\Klipper\\klipper.bin, then run PowerShell:

~~~powershell
$ocd = (Get-ChildItem "C:\OpenOCD" -Filter openocd.exe -Recurse -File | Select-Object -First 1).FullName
Test-Path "C:\Klipper\klipper.bin"
& $ocd -f interface/stlink.cfg -f target/stm32f4x.cfg -c 'adapter speed 100; init; targets; shutdown'
& $ocd -f interface/stlink.cfg -f target/stm32f4x.cfg -c 'adapter speed 100; program C:/Klipper/klipper.bin verify reset exit 0x08000000'
~~~

The first command only probes the SWD connection. The second writes, verifies, resets and exits. Look for **Verified OK**. On Linux, use the same OpenOCD interface/target scripts with a local absolute BIN path.

### 3. Windows: STM32CubeProgrammer

Download [STM32CubeProgrammer](https://www.st.com/en/development-tools/stm32cubeprog.html); select **ST-LINK / SWD**, connect, open **Erasing & Programming**, choose the .bin, enter address **0x08000000**, enable verification, click Download, then reset. Keep the target separately powered.

**Warning:** do not run mass erase or RDP unlock unless you intend to erase existing firmware.

[← All flashing methods](README.md)
