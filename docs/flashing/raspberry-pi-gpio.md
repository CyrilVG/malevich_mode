# Raspberry Pi GPIO → SWD (без USB-программатора / without a USB probe)

## Русский

**Статус:** OpenOCD поддерживает непосредственный SWD через GPIO Raspberry Pi, но **на этой плате такой способ ещё не испытывался**. В отличие от ST-Link и DAPLink, OpenOCD переключает GPIO самого Raspberry Pi; для запуска обычно нужны права root. Перед работой выясните модель Pi и версию OpenOCD.

### 1. Аппаратное подключение

Общая земля Raspberry Pi ↔ GND платы обязательна. GPIO Raspberry Pi рассчитаны только на **логику 3,3 В**: не подавайте в них 5 В или силовое питание принтера. STM32 питается **отдельно**. Перед подключением проводов выключите питание.

Для **современного upstream OpenOCD**, использующего файлы raspberrypi-native.cfg / raspberrypi5-gpiod.cfg и raspberrypi-gpio-connector.cfg, схема такая:

| Raspberry Pi (BCM GPIO) | Физический контакт 40/26-pin | Плата STM32 |
|---|---|---|
| GPIO11 (SWCLK) | **23** | **PA14 / SWCLK** |
| GPIO8 (SWDIO) | **24** | **PA13 / SWDIO** |
| GND | **20** (или любой GND) | GND |

**Критично:** старые версии OpenOCD использовали иную схему, часто GPIO25 → SWCLK (контакт 22), GPIO24 → SWDIO (контакт 18). **Не смешивайте схемы!** Сначала убедитесь, что установленные конфигурационные файлы действительно соответствуют таблице выше. GPIO8/11 могут конфликтовать с SPI; они должны быть свободны.

### 2. Проверить модель Pi и установить OpenOCD

В SSH Raspberry Pi:

~~~bash
cat /proc/device-tree/model; echo
sudo apt-get update
sudo apt-get install openocd
openocd --version
ls /usr/share/openocd/scripts/interface/raspberrypi*-*.cfg
grep -E 'adapter gpio (swclk|swdio)' /usr/share/openocd/scripts/interface/raspberrypi-gpio-connector.cfg
~~~

**Если этих конфигов нет или они показывают другие GPIO, не подключайте по приведённой таблице вслепую.** Установите актуальный OpenOCD с соответствующими интерфейсными скриптами или адаптируйте проводку только после изучения имеющейся конфигурации.

Скопируйте скачанный и проверенный BIN на Raspberry Pi под именем **~/klipper.bin**. Например, в Windows PowerShell (поменяйте имя пользователя/хоста на свои):

~~~powershell
scp .\malevich_mode-stm32f407-v0.1.0.bin pi@raspberrypi.local:~/klipper.bin
~~~

В новой установке Raspberry Pi OS имя пользователя не обязательно будет pi. Приватный Release требует авторизации GitHub перед скачиванием на ПК.

### 3. Raspberry Pi 0/1/2/3/4 / Zero: bcm2835gpio

Для поддерживаемого современного OpenOCD:

~~~bash
sudo openocd -f interface/raspberrypi-native.cfg -f target/stm32f4x.cfg \
  -c 'adapter speed 100; init; targets; shutdown'
~~~

Если соединение установлено, прошейте:

~~~bash
sudo openocd -f interface/raspberrypi-native.cfg -f target/stm32f4x.cfg \
  -c "adapter speed 100; program $HOME/klipper.bin verify reset exit 0x08000000"
~~~

Здесь $HOME раскрывает ваш shell ещё до sudo. Проверьте, что файл действительно существует: ls -lh ~/klipper.bin.

### 4. Raspberry Pi 5: linuxgpiod

В Pi 5 периферия GPIO отличается от Pi 0–4. Нужен **актуальный OpenOCD**, в котором есть файл interface/raspberrypi5-gpiod.cfg и драйвер linuxgpiod. Проверьте соответствие GPIO распиновке конфигурации. Этот драйвер не позволяет вручную задать adapter speed, поэтому параметр скорости здесь не используется:

~~~bash
sudo openocd -f interface/raspberrypi5-gpiod.cfg -f target/stm32f4x.cfg \
  -c 'init; targets; shutdown'
sudo openocd -f interface/raspberrypi5-gpiod.cfg -f target/stm32f4x.cfg \
  -c "program $HOME/klipper.bin verify reset exit 0x08000000"
~~~

Если конфигурации для Pi 5 нет, **не используйте вместо неё raspberrypi-native.cfg**. Обновите OpenOCD и проверьте наличие linuxgpiod.

### 5. Завершение и предупреждения

При успехе ожидается **Verified OK**. Для уже работающего принтера имеет смысл остановить Klipper на время записи, а затем запустить снова:

~~~bash
sudo systemctl stop klipper
# выполните команду программирования выше
sudo systemctl start klipper
~~~

На Pi, обслуживающем несколько MCU, это останавливает управление **всем принтером**, а не только STM32. При необходимости перезапустите отдельное питание платы после записи. **Не соединяйте 3V3/5V GPIO с силовыми цепями принтера.**

Источники: [OpenOCD raspberrypi-native.cfg](https://github.com/openocd-org/openocd/blob/master/tcl/interface/raspberrypi-native.cfg), [актуальная GPIO-карта](https://github.com/openocd-org/openocd/blob/master/tcl/interface/raspberrypi-gpio-connector.cfg), [Raspberry Pi 5 linuxgpiod](https://github.com/openocd-org/openocd/blob/master/tcl/interface/raspberrypi5-gpiod.cfg).

[← Все способы](README.md)

---

## English

**Status:** Raspberry Pi GPIO SWD is supported by OpenOCD but **not yet tested with this particular STM32F407 board**. OpenOCD bit-bangs GPIO directly on the Pi, so elevated privileges and model-specific adapter configuration are usually required.

### 1. Wiring

Turn off power before connecting. Share GND between Pi and STM32; keep the STM32 powered from its own proper supply. **Raspberry Pi GPIO is 3.3 V only**. Do not connect Pi GPIO power pins to the target's power inputs.

For **current upstream OpenOCD** using raspberrypi-native.cfg / raspberrypi5-gpiod.cfg with raspberrypi-gpio-connector.cfg:

| Raspberry Pi BCM GPIO | Physical header pin | STM32 target |
|---|---|---|
| GPIO11 (SWCLK) | **23** | PA14 / SWCLK |
| GPIO8 (SWDIO) | **24** | PA13 / SWDIO |
| GND | **20** or another GND | GND |

**Important:** older OpenOCD scripts often use **GPIO25 on physical pin 22 for SWCLK** and **GPIO24 on physical pin 18 for SWDIO**. Never combine these two pin mappings. Inspect your actual installed OpenOCD scripts before wiring. SPI functions using GPIO8/11 must not be active.

### 2. Install and inspect OpenOCD

~~~bash
cat /proc/device-tree/model; echo
sudo apt-get update
sudo apt-get install openocd
openocd --version
ls /usr/share/openocd/scripts/interface/raspberrypi*-*.cfg
grep -E 'adapter gpio (swclk|swdio)' /usr/share/openocd/scripts/interface/raspberrypi-gpio-connector.cfg
~~~

If these scripts are missing or show different GPIOs, **do not blindly use the wiring table**. Update OpenOCD or follow the wiring explicitly documented by the installed scripts.

Transfer the verified release BIN to your Pi as **~/klipper.bin**, for example from Windows PowerShell (replace the username/hostname):

~~~powershell
scp .\malevich_mode-stm32f407-v0.1.0.bin pi@raspberrypi.local:~/klipper.bin
~~~

The Pi username is not necessarily pi. Downloading a private GitHub Release requires authentication.

### 3. Raspberry Pi 0–4 / Zero: native GPIO

First check the probe:

~~~bash
sudo openocd -f interface/raspberrypi-native.cfg -f target/stm32f4x.cfg \
  -c 'adapter speed 100; init; targets; shutdown'
~~~

Then program:

~~~bash
sudo openocd -f interface/raspberrypi-native.cfg -f target/stm32f4x.cfg \
  -c "adapter speed 100; program $HOME/klipper.bin verify reset exit 0x08000000"
~~~

$HOME expands in your shell before sudo is invoked. Confirm the local file exists.

### 4. Raspberry Pi 5: linuxgpiod

A recent OpenOCD build is needed with **raspberrypi5-gpiod.cfg** and the **linuxgpiod** driver. The bcm2835gpio adapter does **not** support Pi 5. The linuxgpiod driver cannot set a specific adapter speed:

~~~bash
sudo openocd -f interface/raspberrypi5-gpiod.cfg -f target/stm32f4x.cfg \
  -c 'init; targets; shutdown'
sudo openocd -f interface/raspberrypi5-gpiod.cfg -f target/stm32f4x.cfg \
  -c "program $HOME/klipper.bin verify reset exit 0x08000000"
~~~

If the Pi 5 interface script is unavailable, update OpenOCD rather than substituting raspberrypi-native.cfg.

### 5. Post-flash

Look for **Verified OK**, power-cycle the target if necessary, and reconnect Klipper. On a Pi already operating a printer, you may stop Klipper during programming and restart afterward:

~~~bash
sudo systemctl stop klipper
# Run the appropriate OpenOCD command above.
sudo systemctl start klipper
~~~

This interrupts the **entire printer**, including other MCUs. Keep all Raspberry Pi GPIO pins isolated from printer power wiring.

References: [OpenOCD native Pi](https://github.com/openocd-org/openocd/blob/master/tcl/interface/raspberrypi-native.cfg), [OpenOCD GPIO connector pinout](https://github.com/openocd-org/openocd/blob/master/tcl/interface/raspberrypi-gpio-connector.cfg), [OpenOCD Pi 5](https://github.com/openocd-org/openocd/blob/master/tcl/interface/raspberrypi5-gpiod.cfg).

[← All flashing methods](README.md)
