# Установка одной командой / One-command installation

## Русский

Для Raspberry Pi 4 Model B, уже установленного Klipper и платы STM32F407VE
(512 КиБ, кварц 25 МГц, FT232R UART5 PC12/PD2). Устанавливается проверенный
BIN v0.2.0 с драйвером панели и 4 шагами энкодера на щелчок.

До запуска подключите при выключенном питании:

| Физический контакт Raspberry | Плата |
| --- | --- |
| 23 (GPIO11) | PA14 / SWCLK |
| 24 (GPIO8) | PA13 / SWDIO |
| 20 (GND) | GND |

VCC между платами не соединять. Подайте штатное питание на STM32. FT232R
должен быть подключён к Raspberry по USB. SPI0 должен быть отключён.

Запуск от обычного пользователя, например pi, без sudo перед командой:

```bash
bash <(wget -qO- https://raw.githubusercontent.com/CyrilVG/malevich_mode/main/install.sh)
```

Для предварительной проверки без изменений добавьте `--check` в конец.
Пароль sudo может потребоваться при установке. Запуск во время печати запрещён.

Установщик проверяет модель Pi, пути systemd-сервиса и serial-порт; проверяет
SHA256 готовой прошивки; сохраняет конфиги, драйвер и полный дамп 512 КиБ flash;
записывает и проверяет BIN через SWD; устанавливает host-драйвер; настраивает
[mcu] и [display], включая секции в include-файлах; запускает Klipper и ждёт
состояния ready. При ошибке после начала прошивки оставляет Klipper остановленным.

Копии находятся в `~/malevich-backups/ДАТА-ВРЕМЯ/`. Команда возврата:

```bash
python3 ~/malevich-backups/ДАТА-ВРЕМЯ/restore.py
```

Она восстанавливает прежние flash и файлы. Для отката нужны подключённые SWD
провода и питание платы. USB-накопители, бипер, непроверенные силовые выходы не
настраиваются. Существующие конфиги механики сохраняются. На пустой установке
создаётся `kinematics: none`: плата и панель готовы к проверке, но принтер ещё
не готов к печати без настройки осей, температур и защит.

По умолчанию: `~/klipper`, `~/printer_data/config/printer.cfg`,
`~/printer_data/comms/klippy.sock`, сервис `klipper`.
Параметры: `--klipper PATH`, `--config PATH`, `--socket PATH`, `--service NAME`,
`--serial /dev/serial/by-id/...`. Если FT232R несколько, serial обязателен.

Повторная установка снова делает копию и прошивает тот же закреплённый BIN.
После обновления чистого Klipper, удалившего изменение display.py, повторите
команду. Автоматического обновления или фоновой перепрошивки нет.

Проверки: тесты редактирования конфигов и повторного запуска, тесты host-драйвера,
тесты MCU-обработки панели. Прошивка v0.2.0 и ручная запись через Pi проверены
пользователем; полная автоматическая установка на железе ещё требует проверки.

## English

For Raspberry Pi 4 B with Klipper already installed and the STM32F407VE board
(512 KiB flash, 25 MHz HSE, FT232R UART5 PC12/PD2). Connect physical Pi pins
23/24/20 to target SWCLK/SWDIO/GND, supply target power separately, leave VCC
unconnected and disable SPI0. Run the command above as the Klipper user.

The installer verifies the bundled v0.2.0 image, backs up host files and the
entire flash, programs/verifies through SWD, installs the paired panel driver,
updates MCU/display sections and waits for Klipper ready. Encoder uses four
steps per detent. `--check` performs software preflight without modifications.
Backup directories contain restore.py for explicit rollback. Existing machine
configuration is preserved; an empty install gets kinematics:none for panel
testing only. USB storage and unverified machine outputs are not configured.
End-to-end hardware installation testing remains pending.
