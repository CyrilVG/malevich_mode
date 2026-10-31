# Прошивка STM32F407 по SWD / Flashing STM32F407 over SWD

## Русский

Для этой платы **проверенный и поддерживаемый способ записи прошивки — SWD**. Штатный USB-разъём подключён к FT232R и служит для связи Klipper по UART5, но **не питает STM32** и не является штатным интерфейсом записи Flash. Наличие COM-порта или /dev/ttyUSB0 не подтверждает питание MCU.

### Выбор программатора

| Способ | Оборудование | Сложность | Проверено на плате |
|---|---|---|---|
| [ST-Link](st-link.md) | ST-Link V2/V3 + Windows/Linux | Низкая | Стандартный интерфейс, отдельный тест не выполнен |
| [DAPLink / CMSIS-DAP](cmsis-dap.md) | DAPLink + Windows/Linux | Низкая | **Да: запись и Verify OK** |
| [Flipper Zero](flipper-zero.md) | Flipper с приложением DAP Link + ПК | Средняя | Поддержка CMSIS-DAP подтверждена, на этой плате не проверено |
| [Raspberry Pi GPIO](raspberry-pi-gpio.md) | Raspberry Pi 0–5, без USB-программатора | Повышенная | На этой плате не проверено |

Это **мини-вики внутри Git-репозитория** (обычные Markdown-страницы); отдельный GitHub Wiki для проекта не требуется.

### Подключение к плате

| Контакт платы | STM32F407 | Назначение |
|---|---|---|
| SWDIO | PA13 | Двунаправленная линия данных |
| SWCLK | PA14 | Тактирование SWD |
| GND | GND | Общая земля, обязательна |
| Vref / 3V3 | 3,3 В на питаемой плате | Только опорное напряжение *при необходимости*; **не подавать питание в эту точку от программатора** |
| NRST | NRST | Необязателен для обычной записи, полезен при восстановлении |

**Перед подключением проводов выключите питание и проверьте распиновку разъёма мультиметром.** Не путайте логические 3,3 В с силовым питанием принтера. Подавайте на основную плату её **штатное отдельное питание**, соединяйте земли, а линии SWD используйте только с 3,3-вольтовой логикой. Не включайте питание цели одновременно от двух источников.

### Файл прошивки и проверка

Скачайте из [Releases](https://github.com/CyrilVG/malevich_mode/releases) BIN для STM32F407. Адрес записи — **0x08000000**, без дополнительного загрузчика; 512 КиБ Flash, кварц 25 МГц, UART5 250000 бод. После записи ожидается сообщение **Verified OK**, а затем после подачи питания — подключение MCU в Klipper.

В Windows PowerShell (пример для v0.1.0):

~~~powershell
Get-FileHash .\malevich_mode-stm32f407-v0.1.0.bin -Algorithm SHA256
Get-FileHash .\malevich_mode-stm32f407-v0.1.0.bin -Algorithm MD5
~~~

Сравните значения с SHA256SUMS.txt и MD5SUMS.txt из **того же релиза**. В Linux проверьте архив и обе суммы через sha256sum -c / md5sum -c при нахождении файлов в одной папке.

**Защита RDP:** если установлена Level 1, перевод в Level 0 уничтожит текущую пользовательскую Flash. Не выполняйте команду разблокировки или mass erase автоматически. На ранее испытанном экземпляре защита уже снята. RDP Level 2 необратима.

### Если устройство не подключается

1. Проверьте отдельное питание STM32, а не только питание FT232R по USB.
2. Проверьте GND, PA13/SWDIO и PA14/SWCLK; снизьте SWD до 100 кГц.
3. Убедитесь, что выбран target/stm32f4x.cfg и открыт настоящий BIN.
4. Проверьте Verify OK. При необходимости обесточьте/перезапустите плату.
5. Не используйте прошивку через UART5/FT232R вместо SWD: для этого нет подтверждённого загрузчика.

### Источники

- [OpenOCD: Flash programming](https://openocd.org/doc/html/Flash-Programming.html)
- [OpenOCD: Debug adapter configuration](https://openocd.org/doc/html/Debug-Adapter-Configuration.html)
- [Klipper: Bootloaders](https://www.klipper3d.org/Bootloaders.html)

---

## English

For this board the **validated firmware flashing interface is SWD**. Its on-board USB connector reaches the FT232R and communicates with Klipper through UART5; it **does not power the STM32** and cannot be assumed to provide an MCU bootloader.

### Choose a programming method

| Method | Hardware | Complexity | Tested on this board |
|---|---|---|---|
| [ST-Link](st-link.md) | ST-Link V2/V3 + Windows/Linux | Easy | Supported adapter; board test not performed |
| [DAPLink / CMSIS-DAP](cmsis-dap.md) | CMSIS-DAP probe + Windows/Linux | Easy | **Yes: programming and verification** |
| [Flipper Zero](flipper-zero.md) | DAP Link app + USB-connected computer | Intermediate | CMSIS-DAP support confirmed; board test pending |
| [Raspberry Pi GPIO](raspberry-pi-gpio.md) | Raspberry Pi 0–5 GPIO, no USB probe | Advanced | Board test pending |

These guides form a **small wiki-style documentation section in the repository**.

### Target wiring

| Target signal | STM32F407 pin | Notes |
|---|---|---|
| SWDIO | PA13 | Bidirectional SWD data |
| SWCLK | PA14 | SWD clock |
| GND | GND | Required shared ground |
| Vref / 3V3 | Powered target's regulated 3.3 V | Voltage reference **only if required**; do **not** power this board through the probe |
| NRST | NRST | Optional for ordinary flashing; useful for recovery |

**Disconnect power before wiring. Verify your connector pinout with a multimeter.** The target needs its normal independent board supply and a shared GND. SWD operates at 3.3 V logic; never feed 5 V into GPIO, SWD, or target reference pins.

### Firmware image and integrity

Download the STM32F407 BIN from [Releases](https://github.com/CyrilVG/malevich_mode/releases). Flash it at **0x08000000** with no application bootloader. This board has 512 KiB of Flash, a 25 MHz HSE and UART5 at 250000 baud.

On Windows PowerShell:

~~~powershell
Get-FileHash .\malevich_mode-stm32f407-v0.1.0.bin -Algorithm SHA256
Get-FileHash .\malevich_mode-stm32f407-v0.1.0.bin -Algorithm MD5
~~~

Compare with the checksum files from the **same release**. Verify OK in OpenOCD confirms the image was read back and matched.

**RDP warning:** lowering read protection from Level 1 to Level 0 erases existing user Flash. Do not perform an unlock or mass erase by default. The previously tested board is already at Level 0; Level 2 cannot be reversed.

### Troubleshooting

Check the separate MCU power supply, shared ground, SWDIO/clock wiring, stm32f4x target configuration and the image address. Start with a 100 kHz SWD speed, and power-cycle if needed after verifying the image. UART5 through FT232R is **not** a known firmware programming path.

### References

- [OpenOCD flash programming](https://openocd.org/doc/html/Flash-Programming.html)
- [OpenOCD debug adapter configuration](https://openocd.org/doc/html/Debug-Adapter-Configuration.html)
- [Klipper bootloaders](https://www.klipper3d.org/Bootloaders.html)
