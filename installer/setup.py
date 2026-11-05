#!/usr/bin/env python3
"""PICASO STM32F407 / Raspberry Pi 4 installer. Standard library only."""
import argparse
import base64
import datetime
import glob
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time

FIRMWARE_SHA = '4704cc2d51ad55adbc388a45e8795644ef4992acdf39cbecdcf11c52bdf8fbb5'
HEADER = re.compile(r'^[ \t]*\[([^\]\n]+)\][ \t]*(?:[#;].*)?$', re.M)
DISPLAY = '''[display]
lcd_type: malevich_panel
encoder_steps_per_detent: 4
panel_reverse_encoder: False
contrast: 239
invert: False
'''
SWD = '''source [find interface/raspberrypi-native.cfg]
transport select swd
adapter gpio swclk 11
adapter gpio swdio 8
source [find target/stm32f4x.cfg]
reset_config none
adapter speed 100
'''

def run(args, **kw):
    return subprocess.run([str(x) for x in args], check=True, **kw)

def sections(text):
    matches = list(HEADER.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        # Never consume Klipper's SAVE_CONFIG footer.
        footer = text.find('#*#', m.end(), end)
        if footer >= 0:
            end = footer
        yield m.group(1).strip(), m.start(), end

def load_configs(root):
    result = {}
    active = set()
    def visit(path):
        path = path.resolve()
        if path in active:
            raise ValueError('Циклический include: ' + str(path))
        if path in result:
            raise ValueError('Повторный include: ' + str(path))
        text = path.read_text() if path.exists() else ''
        if not path.exists() and path != root.resolve():
            raise ValueError('Файл include не найден: ' + str(path))
        result[path] = text
        active.add(path)
        for name, _, _ in sections(text):
            if name.startswith('include '):
                pattern = name[8:].strip()
                paths = sorted(glob.glob(str(path.parent / pattern)))
                if not paths and not glob.has_magic(pattern):
                    raise ValueError('Include не найден: ' + pattern)
                for child in paths:
                    visit(Path(child))
        active.remove(path)
    visit(root)
    return result

def plan_config(root, serial, gcodes):
    files = load_configs(root)
    found = {}
    for path, text in files.items():
        for name, start, end in sections(text):
            if name.startswith('include '):
                continue
            if name in found:
                # Klipper merges repeated sections across [include] files.
                # Only edits to duplicate MCU/display sections are ambiguous.
                if name in ('mcu', 'display'):
                    raise ValueError('Повторная секция: [' + name + ']')
                continue
            found[name] = path
    # Refuse unexpected old virtual-pin users rather than remove unrelated config.
    for path, text in files.items():
        for name, start, end in sections(text):
            if name != 'display' and re.search(r'(?m)^\s*[^#;\n][^\n]*hc165:', text[start:end]):
                raise ValueError('Вне [display] остались hc165-пины: ' + name)
    display = DISPLAY
    if 'display' in found:
        text = files[found['display']]
        _, start, end = next(x for x in sections(text) if x[0] == 'display')
        # Retain presentation and navigation preferences, not old physical pins.
        keep = ('menu_root', 'menu_timeout', 'menu_reverse_navigation',
                'display_group', 'encoder_fast_rate', 'panel_reverse_encoder',
                'contrast', 'invert')
        for key in keep:
            match = re.search(r'(?m)^[ \t]*' + key + r'[ \t]*[:=][^\n]*', text[start:end])
            if match:
                display = re.sub(r'(?m)^' + key + r':[^\n]*\n', '', display)
                display += match.group(0).strip() + '\n'
    replacements = {'display': display}
    mcu = '[mcu]\nserial: ' + serial + '\nbaud: 250000\nrestart_method: command\n'
    if 'mcu' in found:
        text = files[found['mcu']]
        _, start, end = next(s for s in sections(text) if s[0] == 'mcu')
        # Preserve additional MCU options; replace only transport fields.
        old = text[start:end]
        old = re.sub(r'(?mi)^[ \t]*(serial|baud|restart_method|canbus_uuid)\s*[:=].*\n?', '', old)
        mcu = old.rstrip() + '\nserial: ' + serial + '\nbaud: 250000\nrestart_method: command\n'
    replacements['mcu'] = mcu
    additions = {
        'printer': '[printer]\nkinematics: none\nmax_velocity: 1\nmax_accel: 1\n',
        'virtual_sdcard': '[virtual_sdcard]\npath: ' + str(gcodes) + '\n',
        'pause_resume': '[pause_resume]\n',
        'display_status': '[display_status]\n',
        'respond': '[respond]\n',
    }
    root = root.resolve()
    for name, content in replacements.items():
        path = found.get(name, root)
        if name in found:
            _, start, end = next(s for s in sections(files[path]) if s[0] == name)
            files[path] = files[path][:start] + content + '\n' + files[path][end:]
        else:
            additions[name] = content
    extra = '\n'.join(value for name, value in additions.items() if name not in found)
    if extra:
        text = files[root]
        pos = text.find('#*#')
        if pos < 0:
            pos = len(text)
        files[root] = text[:pos].rstrip() + '\n\n' + extra + '\n' + text[pos:]
    return files

def driver_plan(klipper, payload):
    dest = klipper / 'klippy/extras/display/display.py'
    text = dest.read_text()
    entry = "    'malevich_panel': malevich_panel.MalevichPanel,"
    if entry not in text:
        if text.count('LCD_chips = {') != 1:
            raise ValueError('Неподдерживаемая версия display.py')
        text = text.replace('LCD_chips = {', 'from . import malevich_panel\n\nLCD_chips = {\n' + entry, 1)
    compile(text, str(dest), 'exec')
    module = (payload / 'panel/host/malevich_panel.py').read_text()
    compile(module, 'malevich_panel.py', 'exec')
    return {dest: text, dest.parent / 'malevich_panel.py': module}

def ready(sockpath, timeout=60):
    deadline = time.monotonic() + timeout
    last = 'Нет ответа Klipper API'
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(2)
                sock.connect(str(sockpath))
                sock.sendall(b'{"id":1,"method":"info","params":{}}\x03')
                data = b''
                while b'\x03' not in data:
                    chunk = sock.recv(65536)
                    if not chunk:
                        raise OSError('API disconnected')
                    data += chunk
                result = json.loads(data.split(b'\x03')[0]).get('result', {})
                last = result.get('state_message', str(result))
                if result.get('state') == 'ready':
                    return
        except (OSError, ValueError) as exc:
            last = str(exc)
        time.sleep(1)
    raise RuntimeError('Klipper не перешёл в ready: ' + last)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--serial', help='Точный путь /dev/serial/by-id/...')
    p.add_argument('--klipper', type=Path, default=Path.home() / 'klipper')
    p.add_argument('--config', type=Path, default=Path.home() / 'printer_data/config/printer.cfg')
    p.add_argument('--socket', type=Path, default=Path.home() / 'printer_data/comms/klippy.sock')
    p.add_argument('--service', default='klipper')
    p.add_argument('--check', action='store_true', help='Проверить окружение и показать план без изменений')
    a = p.parse_args()
    if os.geteuid() == 0:
        raise ValueError('Запускайте от пользователя pi без sudo; sudo будет вызван для нужных операций.')
    model = Path('/proc/device-tree/model').read_text().rstrip('\x00')
    if not model.startswith('Raspberry Pi 4 Model B'):
        raise ValueError('Этот установщик проверен для Raspberry Pi 4 Model B. Обнаружено: ' + model)
    if not re.fullmatch(r'[\w@.-]+', a.service):
        raise ValueError('Некорректное имя сервиса')
    payload = Path(__file__).resolve().parents[1]
    firmware = base64.b64decode((payload / 'installer/firmware.bin.b64').read_bytes())
    if hashlib.sha256(firmware).hexdigest() != FIRMWARE_SHA:
        raise ValueError('Контрольная сумма BIN не совпала')
    candidates = sorted(glob.glob('/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_*-if00-port0'))
    if a.serial:
        serial = a.serial
    elif len(candidates) == 1:
        serial = candidates[0]
    else:
        raise ValueError('Нужен ровно один FT232R; укажите --serial /dev/serial/by-id/...')
    if not serial.startswith('/dev/serial/by-id/') or not Path(serial).exists() or any(c.isspace() for c in serial):
        raise ValueError('Некорректный или отсутствующий serial-порт')
    cmd = run(['systemctl', 'show', a.service, '-p', 'ExecStart', '--value'], capture_output=True, text=True).stdout
    # Inspect the loaded service, including systemd EnvironmentFile expansion.
    expanded = cmd
    envfiles = run(['systemctl', 'show', a.service, '-p', 'EnvironmentFiles', '--value'], capture_output=True, text=True).stdout
    for filename in re.findall(r'(\S+)\s+\(ignore_errors=', envfiles):
        for line in Path(filename).read_text().splitlines():
            if re.match(r'^\s*[A-Za-z_][A-Za-z_0-9]*=', line):
                key, value = line.split('=', 1)
                parts = shlex.split(value)
                expanded = expanded.replace('${' + key.strip() + '}', ' '.join(parts)).replace('$' + key.strip(), ' '.join(parts))
    for required in (a.klipper.resolve() / 'klippy/klippy.py', a.config.resolve(), a.socket.resolve()):
        if str(required) not in expanded:
            raise ValueError('Сервис использует другие пути; укажите --klipper/--config/--socket. ExecStart: ' + expanded)
    # GPIO8/11 must not be owned by SPI overlays.
    if glob.glob('/dev/spidev0.*'):
        raise ValueError('SPI0 включён. Отключите SPI в raspi-config и перезагрузите Raspberry.')
    gcodes = a.config.resolve().parent.parent / 'gcodes'
    planned = plan_config(a.config, serial, gcodes)
    planned.update(driver_plan(a.klipper, payload))
    print('Плата: STM32F407VE; Pi:', model)
    print('SWD: физ.23 -> PA14, физ.24 -> PA13, физ.20 -> GND; VCC не подключать.')
    print('BIN v0.2.0:', FIRMWARE_SHA)
    print('Serial:', serial)
    print('Будут настроены MCU и панель, энкодер: 4. Существующие оси/нагреватели сохраняются.')
    print('Если конфигурации осей нет: тестовый режим kinematics: none, без управления движением/нагревом.')
    print('Файлы:', '\n'.join(str(x) for x in planned))
    if a.check:
        print('Проверка завершена; изменений нет.')
        return
    lock = (Path.home() / '.malevich-install.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise ValueError('Установка уже выполняется')
    run(['sudo', '-v'])
    if not shutil.which('openocd'):
        run(['sudo', 'apt-get', 'update'])
        run(['sudo', 'apt-get', 'install', '-y', 'openocd'])
    for name in ('interface/raspberrypi-native.cfg', 'target/stm32f4x.cfg'):
        if not (Path('/usr/share/openocd/scripts') / name).is_file():
            raise ValueError('В OpenOCD отсутствует ' + name)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = Path.home() / 'malevich-backups' / stamp
    backup.mkdir(parents=True, mode=0o700)
    manifest = {}
    for i, path in enumerate(planned):
        key = 'file-' + str(i)
        manifest[str(path)] = key if path.exists() else None
        if path.exists():
            shutil.copy2(path, backup / key)
    (backup / 'files.json').write_text(json.dumps(manifest, indent=2))
    (backup / 'stm32-swd.cfg').write_text(SWD)
    (backup / 'new.bin').write_bytes(firmware)
    (backup / 'restore.py').write_text((payload / 'installer/restore.py').read_text())
    print('Резервные копии и журнал:', backup, flush=True)
    if a.socket.exists():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(3)
            sock.connect(str(a.socket))
            sock.sendall(b'{"id":1,"method":"objects/query","params":{"objects":{"print_stats":null,"idle_timeout":null}}}\x03')
            data = b''
            while b'\x03' not in data:
                chunk = sock.recv(65536)
                if not chunk:
                    raise ValueError('Не удалось проверить состояние печати')
                data += chunk
            status = json.loads(data.split(b'\x03')[0]).get('result', {}).get('status', {})
            if (status.get('print_stats', {}).get('state') in ('printing', 'paused')
                or status.get('idle_timeout', {}).get('state') == 'Printing'):
                raise ValueError('Сначала завершите печать/движение; установка остановлена')
    was_active = subprocess.run(['systemctl', 'is-active', '--quiet', a.service]).returncode == 0
    touched = False
    try:
        run(['sudo', 'systemctl', 'stop', a.service])
        with (backup / 'openocd.log').open('w') as log:
            # Halt, verify silicon/flash size, make FULL backup, then resume.
            probe = ('init; halt; '
                     'set id [mrw 0xe0042000]; '
                     'if {($id & 0xfff) != 0x413} {error "Not STM32F407/405"}; '
                     'set fs [mrh 0x1fff7a22]; '
                     'if {$fs != 512} {error "Expected 512 KiB flash"}; '
                     'dump_image previous.bin 0x08000000 0x80000; reset run; shutdown')
            run(['sudo','openocd','-f','stm32-swd.cfg','-c',probe], cwd=backup, stdout=log, stderr=subprocess.STDOUT)
            if (backup / 'previous.bin').stat().st_size != 524288:
                raise ValueError('Неполная резервная копия flash')
            touched = True
            run(['sudo','openocd','-f','stm32-swd.cfg','-c',
                 'program new.bin verify reset exit 0x08000000'], cwd=backup, stdout=log, stderr=subprocess.STDOUT)
        for path, text in planned.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.name + '.malevich-new')
            temp.write_text(text)
            if path.exists():
                shutil.copymode(path, temp)
            os.replace(temp, path)
        gcodes.mkdir(parents=True, exist_ok=True)
        run(['sudo','systemctl','start',a.service])
        ready(a.socket)
        print('ГОТОВО: Klipper ready. В Fluidd проверьте HC_PANEL_STATUS.')
        print('Откат: python3', backup / 'restore.py', '--service', a.service)
    except BaseException:
        if touched:
            subprocess.run(['sudo','systemctl','stop',a.service])
            print('Установка не завершена; Klipper остановлен. Откат: python3', backup / 'restore.py', '--service', a.service, file=sys.stderr)
        elif was_active:
            subprocess.run(['sudo','openocd','-f',str(backup/'stm32-swd.cfg'),'-c','init; reset run; shutdown'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(['sudo','systemctl','start',a.service])
        print('Диагностика:', backup / 'openocd.log', file=sys.stderr)
        raise

if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit('Ошибка: ' + str(exc))
