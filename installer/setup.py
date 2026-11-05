#!/usr/bin/env python3
"""PICASO STM32F407 installer for supported Raspberry Pi hosts."""
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
FIRMWARE_SHA_BY_MODEL = {'X': FIRMWARE_SHA, 'XL': None}
PANEL_FILES = (
    'README.md', 'display.cfg', 'install.py',
    'host/malevich_panel.py',
    'src/malevich_panel.c', 'src/malevich_logo.h',
    'tests/test_host.py', 'tests/test_panel.c',
    'tests/stubs/board/gpio.h', 'tests/stubs/board/irq.h',
    'tests/stubs/board/misc.h', 'tests/stubs/command.h',
    'tests/stubs/sched.h',
)
HEADER = re.compile(r'^[ \t]*\[([^\]\n]+)\][ \t]*(?:[#;].*)?$', re.M)
DISPLAY = '''[display]
lcd_type: malevich_panel
encoder_steps_per_detent: 4
panel_reverse_encoder: False
contrast: 239
invert: False
'''
SWD_NATIVE = '''source [find interface/raspberrypi-native.cfg]
transport select swd
adapter gpio swclk 11
adapter gpio swdio 8
source [find target/stm32f4x.cfg]
reset_config none
adapter speed 100
'''
SWD_PI5 = '''source [find interface/raspberrypi5-gpiod.cfg]
transport select swd
source [find target/stm32f4x.cfg]
reset_config none
'''

def run(args, **kw):
    return subprocess.run([str(x) for x in args], check=True, **kw)

def color(text, code):
    if not sys.stdout.isatty() or os.environ.get('NO_COLOR'):
        return text
    return '\033[' + code + 'm' + text + '\033[0m'

def ask_choice(title, options, default=None):
    print(color(title, '96'))
    for key, label in options:
        suffix = ' (определена)' if key == default else ''
        print('  ' + color(key + ')', '92') + ' ' + label + suffix)
    prompt = 'Выбор'
    if default:
        prompt += ' [Enter = ' + default + ']'
    return input(color(prompt + ': ', '93')).strip() or (default or '')

def sections(text):
    matches = list(HEADER.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        # Never consume Klipper's SAVE_CONFIG footer.
        footer = text.find('#*#', m.end(), end)
        if footer >= 0:
            end = footer
        yield m.group(1).strip(), m.start(), end

def load_configs(root, staged=None):
    staged = {Path(path).resolve(): text for path, text in (staged or {}).items()}
    result = {}
    active = set()
    def visit(path):
        path = path.resolve()
        if path in active:
            raise ValueError('Циклический include: ' + str(path))
        if path in result:
            # Klipper allows the same file to be reached from more than one
            # include path; its parser only rejects a file included recursively.
            return
        exists = path.exists() or path in staged
        text = staged.get(path, path.read_text() if path.exists() else '')
        if not exists and path != root.resolve():
            raise ValueError('Файл include не найден: ' + str(path))
        result[path] = text
        active.add(path)
        for name, _, _ in sections(text):
            if name.startswith('include '):
                pattern = name[8:].strip()
                paths = sorted(glob.glob(str(path.parent / pattern)))
                staged_path = (path.parent / pattern).resolve()
                if staged_path in staged and str(staged_path) not in paths:
                    paths.append(str(staged_path))
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
    occurrences = {}
    for path, text in files.items():
        for name, start, end in sections(text):
            if name.startswith('include '):
                continue
            found.setdefault(name, path)
            occurrences.setdefault(name, []).append((path, start, end))
    # A user config can reach the same included tree from more than one place.
    # Leave unrelated duplicate sections untouched; only transport/display
    # sections must be unique because this installer replaces them below.
    for name, instances in occurrences.items():
        if len(instances) > 1 and name in ('mcu', 'display'):
            paths = [path for path, _, _ in instances]
            raise ValueError('Повторная секция: [' + name + '] в ' + ', '.join(map(str, paths)))

    for path, text in files.items():
        for name, start, end in sections(text):
            if name != 'display' and re.search(r'(?m)^\s*[^#;\n][^\n]*hc165:', text[start:end]):
                raise ValueError('Вне [display] остались hc165-пины: ' + name)
    # Replace the entire physical display configuration with display.cfg.
    # User menu sections remain separate Klipper sections and are preserved.
    replacements = {'display': DISPLAY}
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

def install_x_profile(config, serial, gcodes, payload):
    config = config.resolve()
    config_dir = config.parent
    profile = payload / 'profiles/designer_x/printer.cfg'
    pins = payload / 'profiles/designer_x/board_pins.cfg'
    if not profile.is_file() or not pins.is_file():
        raise ValueError('В комплекте отсутствует полный профиль Designer X')
    cfg = profile.read_text()
    if cfg.count('@MCU_SERIAL@') != 1:
        raise ValueError('Профиль Designer X не содержит маркер serial-порта')
    if '[include fluidd.cfg]' not in cfg or '[include board_pins.cfg]' not in cfg:
        raise ValueError('Профиль Designer X должен подключать fluidd.cfg и board_pins.cfg')
    cfg = cfg.replace('@MCU_SERIAL@', serial)
    cfg = cfg.replace('/home/pi/printer_data/gcodes', str(gcodes))
    display_range = next(((start, end) for name, start, end in sections(cfg)
                          if name == 'display'), None)
    if display_range:
        start, end = display_range
        cfg = cfg[:start] + DISPLAY + '\n' + cfg[end:]
    else:
        cfg = cfg.rstrip() + '\n\n' + DISPLAY

    board_pins_path = (config_dir / 'board_pins.cfg').resolve()
    planned = {
        config: cfg,
        board_pins_path: pins.read_text(),
    }
    # Inspect the complete include tree, but do not rewrite fluidd.cfg: it can
    # be a symlink into fluidd-config/client.cfg, outside printer_data/config.
    files = load_configs(config, planned)
    included_sections = [name for text in files.values()
                         for name, _, _ in sections(text)]
    for name, block in (
        ('virtual_sdcard', '[virtual_sdcard]\npath: ' + str(gcodes) + '\n'),
        ('pause_resume', '[pause_resume]\n'),
        ('display_status', '[display_status]\n'),
        ('respond', '[respond]\n'),
    ):
        if name not in included_sections:
            cfg = cfg.rstrip() + '\n\n' + block
            included_sections.append(name)
    virtual_sd_sections = [text[start:end] for text in files.values()
                           for name, start, end in sections(text)
                           if name == 'virtual_sdcard']
    if virtual_sd_sections and not any(re.search(r'(?mi)^\s*path\s*[:=]', block)
                                       for block in virtual_sd_sections):
        cfg = cfg.rstrip() + '\n\n[virtual_sdcard]\npath: ' + str(gcodes) + '\n'
    planned = {
        config: cfg,
        board_pins_path: pins.read_text(),
    }
    files = load_configs(config, planned)
    seen = {}
    critical_sections = {'display', 'mcu'}
    for path, text in files.items():
        for name, _, _ in sections(text):
            if name.startswith('include '):
                continue
            if name in seen and (name in critical_sections or name.startswith('board_pins')):
                raise ValueError('Профиль X содержит повторную секцию [' + name +
                                 '] в ' + str(seen[name]) + ' и ' + str(path))
            seen.setdefault(name, path)
    return planned

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

def panel_bundle_plan(payload):
    source = payload / 'panel'
    target = Path.home() / 'panel'
    planned = {}
    for relative in PANEL_FILES:
        src = source / relative
        if not src.is_file():
            raise ValueError('В комплекте отсутствует panel/' + relative)
        planned[target / relative] = src.read_text()
    display_cfg = (source / 'display.cfg').read_text()
    normalize = lambda text: [line.strip() for line in text.splitlines()
                              if line.strip() and not line.lstrip().startswith('#')]
    if normalize(display_cfg) != normalize(DISPLAY):
        raise ValueError('panel/display.cfg не совпадает с конфигурацией [display] установщика')
    return planned

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
    p.add_argument('--host-board', choices=['pi3','pi4','pi5','opi3lts','opi5','opi5plus'], help='Модель одноплатника')
    p.add_argument('--printer-model', choices=['X','XL'], help='Модель принтера')
    config_group = p.add_mutually_exclusive_group()
    config_group.add_argument('--install-x-config', action='store_true', help='Установить профиль Designer X из комплекта')
    config_group.add_argument('--keep-config', action='store_true', help='Оставить текущий конфиг принтера вместо профиля X')
    p.add_argument('--klipper', type=Path, default=Path.home() / 'klipper')
    p.add_argument('--config', type=Path, default=Path.home() / 'printer_data/config/printer.cfg')
    p.add_argument('--socket', type=Path, default=Path.home() / 'printer_data/comms/klippy.sock')
    p.add_argument('--service', default='klipper')
    p.add_argument('--check', action='store_true', help='Проверить окружение и показать план без изменений')
    a = p.parse_args()
    if os.geteuid() == 0:
        raise ValueError('Запускайте от пользователя pi без sudo; sudo будет вызван для нужных операций.')
    try:
        detected_model = Path('/proc/device-tree/model').read_text().rstrip('\x00')
    except OSError:
        detected_model = ''
    boards = {
        'pi3':'Raspberry Pi 3 (GPIO11 SWCLK, GPIO8 SWDIO)',
        'pi4':'Raspberry Pi 4 (GPIO11 SWCLK, GPIO8 SWDIO)',
        'pi5':'Raspberry Pi 5 (RP1 GPIO11 SWCLK, GPIO8 SWDIO)',
        'opi3lts':'Orange Pi 3 LTS (SWD GPIO mapping not validated)',
        'opi5':'Orange Pi 5 (SWD GPIO mapping not validated)',
        'opi5plus':'Orange Pi 5 Plus (SWD GPIO mapping not validated)',
    }
    board_options = [
        ('1', 'Raspberry Pi 3'),
        ('2', 'Raspberry Pi 4'),
        ('3', 'Raspberry Pi 5'),
        ('4', 'Orange Pi 3 LTS'),
        ('5', 'Orange Pi 5'),
        ('6', 'Orange Pi 5 Plus'),
    ]
    aliases = {'1':'pi3','2':'pi4','3':'pi5','4':'opi3lts','5':'opi5','6':'opi5plus'}
    detected_board = ('pi3' if 'Raspberry Pi 3' in detected_model else
                      'pi4' if 'Raspberry Pi 4' in detected_model else
                      'pi5' if 'Raspberry Pi 5' in detected_model else None)
    board = a.host_board or detected_board
    if not a.host_board and sys.stdin.isatty():
        detected_choice = next((key for key, value in aliases.items() if value == board), None)
        choice = ask_choice('Выберите одноплатник:', board_options, detected_choice)
        if choice:
            board = aliases.get(choice)
    elif not board:
        raise ValueError('Не удалось определить одноплатник. Укажите --host-board pi3|pi4|pi5|opi3lts|opi5|opi5plus')
    if board not in boards:
        raise ValueError('Модель одноплатника не выбрана')
    print('Одноплатник:', boards[board])
    if board.startswith('opi'):
        print('Для этого Orange Pi пока нет проверенной распиновки и профиля GPIO для OpenOCD; флеш и конфиги не изменены.')
        raise ValueError('SWD пока поддержан только на Raspberry Pi 3, 4 и 5')
    print('Подключение SWD (питание выключено): Raspberry pin 23 / GPIO11 -> PA14/SWCLK;')
    print('Raspberry pin 24 / GPIO8 -> PA13/SWDIO; pin 20 -> GND. VCC не подключать.')
    payload = Path(__file__).resolve().parents[1]
    if a.printer_model:
        printer_model = a.printer_model
    elif sys.stdin.isatty():
        printer_choice = ask_choice('Выберите модель принтера:', [
            ('1', 'Designer X'),
            ('2', 'Designer XL'),
        ])
        printer_model = {'1':'X', '2':'XL'}.get(printer_choice, printer_choice.upper())
    else:
        raise ValueError('Укажите модель принтера флагом --printer-model X или XL')
    if printer_model in ('1','X'): printer_model='X'
    elif printer_model in ('2','XL'): printer_model='XL'
    else: raise ValueError('Модель принтера не выбрана')
    firmware_by_model = {
        'X': payload / 'installer/firmware.bin.b64',
        'XL': payload / 'firmware/designer_xl/klipper.bin',
    }
    profile_by_model = {
        'X': payload / 'profiles/designer_x/printer.cfg',
        'XL': payload / 'profiles/designer_xl/printer.cfg',
    }
    if printer_model == 'XL':
        missing = [path for path in (firmware_by_model['XL'], profile_by_model['XL']) if not path.is_file()]
        raise ValueError('Designer XL выбран, но комплект XL ещё не опубликован (' +
                         ', '.join(str(path.relative_to(payload)) for path in missing) +
                         '). Установка остановлена до изменения файлов и прошивки.')
    install_x_config = not a.keep_config
    if a.install_x_config:
        install_x_config = True
    elif a.printer_model is None and sys.stdin.isatty() and not a.keep_config:
        answer = input(color('Установить профиль конфигурации Designer X из комплекта? Текущие файлы будут сохранены в резервную копию [Y/n]: ', '93')).strip().lower()
        install_x_config = answer not in ('n', 'no')

    if not re.fullmatch(r'[\w@.-]+', a.service):
        raise ValueError('Некорректное имя сервиса')
    firmware_data = firmware_by_model[printer_model].read_bytes()
    firmware = (base64.b64decode(firmware_data) if firmware_by_model[printer_model].suffix == '.b64'
                else firmware_data)
    expected_sha = FIRMWARE_SHA_BY_MODEL[printer_model]
    if expected_sha is None:
        raise ValueError('Для Designer ' + printer_model + ' ещё не закреплена проверенная SHA256 прошивки')
    if hashlib.sha256(firmware).hexdigest() != expected_sha:
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
    planned = (install_x_profile(a.config, serial, gcodes, payload) if install_x_config
               else plan_config(a.config, serial, gcodes))
    planned.update(driver_plan(a.klipper, payload))
    planned.update(panel_bundle_plan(payload))
    print('Плата: STM32F407VE; одноплатник:', boards[board], '|', detected_model or board)
    print('OpenOCD профиль:', 'Pi 5 linuxgpiod' if board == 'pi5' else 'Pi 3/4 native GPIO')
    print('BIN v0.2.0:', expected_sha)
    print('Принтер: Designer', printer_model, '| конфигурация:', 'профиль X из комплекта' if install_x_config else 'текущий printer.cfg сохраняется')
    print('Serial:', serial)
    if install_x_config:
        print('Профиль X заменит printer.cfg и карту board_pins.cfg; прежние файлы попадут в резервную копию.')
    else:
        print('Существующие оси/нагреватели сохраняются; будут обновлены MCU и панель.')
    print('Панель: полный комплект будет установлен в', Path.home() / 'panel')
    print('Конфигурация [display]:\n' + DISPLAY.rstrip())
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
    interface = 'interface/raspberrypi5-gpiod.cfg' if board == 'pi5' else 'interface/raspberrypi-native.cfg'
    openocd_files = [interface, 'target/stm32f4x.cfg']
    if board == 'pi5':
        openocd_files.append('interface/raspberrypi-gpio-connector.cfg')
    for name in openocd_files:
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
    swd_cfg = SWD_PI5 if board == 'pi5' else SWD_NATIVE
    (backup / 'stm32-swd.cfg').write_text(swd_cfg)
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
