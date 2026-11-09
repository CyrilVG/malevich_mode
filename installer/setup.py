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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from autodetect import DetectionError, parse_model, scan_printer

INSTALLER_VERSION = '0.3.3'
FIRMWARE_SHA_BY_MODEL = {
    'X': '4704cc2d51ad55adbc388a45e8795644ef4992acdf39cbecdcf11c52bdf8fbb5',
    # Klipper's bank selection is a host config feature, so these model-specific
    # artifacts are intentionally separate paths but currently identical images.
    'XL': '4704cc2d51ad55adbc388a45e8795644ef4992acdf39cbecdcf11c52bdf8fbb5',
}
AUTODETECT_SHA = '8bc01b5614f6078dd32ef8d54cb51234c24152e4f22ad206d0c666d9d2b3d79a'
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


class InstallPlan(dict):
    """File changes plus existing config files that need adjacent backups."""
    def __init__(self, *args, backup_paths=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.backup_paths = set(backup_paths)


def cfg_backup_path(path):
    path = Path(path)
    candidate = path.with_name(path.name + '.backup')
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(path.name + '.backup.' + str(suffix))
        suffix += 1
    return candidate


def remove_section_ranges(text, ranges):
    for start, end in sorted(ranges, reverse=True):
        text = text[:start] + text[end:]
    return text


def set_config_section(text, name, block):
    ranges = [(start, end) for section, start, end in sections(text)
              if section == name]
    if ranges:
        text = remove_section_ranges(text, ranges)
    pos = text.find('#*#')
    if pos < 0:
        pos = len(text)
    return text[:pos].rstrip() + '\n\n' + block.rstrip() + '\n' + text[pos:]

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


def ask_yes_no(prompt, default=False):
    suffix = '[Y/n]' if default else '[y/N]'
    answer = input(color(prompt + ' ' + suffix + ': ', '93')).strip().lower()
    if not answer:
        return default
    return answer in ('y', 'yes', 'д', 'да')

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

def install_profile(config, serial, gcodes, payload, model):
    config = config.resolve()
    config_dir = config.parent
    profile_dir = payload / 'profiles' / ('designer_x' if model == 'X' else 'designer_xl')
    profile = profile_dir / 'printer.cfg'
    pins = profile_dir / 'board_pins.cfg'
    macros = profile_dir / 'macros.cfg'
    if not all(path.is_file() for path in (profile, pins, macros)):
        raise ValueError('В комплекте отсутствует полный профиль Designer ' + model)
    cfg = profile.read_text()
    if cfg.count('@MCU_SERIAL@') != 1:
        raise ValueError('Профиль Designer ' + model + ' не содержит маркер serial-порта')
    for required_include in ('[include fluidd.cfg]', '[include board_pins.cfg]', '[include macros.cfg]'):
        if required_include not in cfg:
            raise ValueError('Профиль Designer ' + model + ' должен подключать ' + required_include)
    cfg = cfg.replace('@MCU_SERIAL@', serial)
    cfg = cfg.replace('@GCODE_PATH@', str(gcodes))
    cfg = cfg.replace('/home/pi/printer_data/gcodes', str(gcodes))
    display_range = next(((start, end) for name, start, end in sections(cfg)
                          if name == 'display'), None)
    if display_range:
        start, end = display_range
        cfg = cfg[:start] + DISPLAY + '\n' + cfg[end:]
    else:
        cfg = cfg.rstrip() + '\n\n' + DISPLAY

    board_pins_path = (config_dir / 'board_pins.cfg').resolve()
    macros_path = (config_dir / 'macros.cfg').resolve()
    # Install the Klipper services required by the supplied macros and UI.
    # The profile owns these sections so old Fluidd copies are removed below.
    for name, block in (
        ('virtual_sdcard', '[virtual_sdcard]\npath: ' + str(gcodes) + '\n'),
        ('pause_resume', '[pause_resume]\n'),
        ('display_status', '[display_status]\n'),
        ('respond', '[respond]\n'),
    ):
        cfg = set_config_section(cfg, name, block)
    planned = {
        config: cfg,
        board_pins_path: pins.read_text(),
        macros_path: macros.read_text(),
    }
    # Inspect the complete include tree, but preserve the source files before
    # removing any section that duplicates this profile.
    files = load_configs(config, planned)
    owned_paths = set(planned)
    owned_sections = {
        name
        for path, text in planned.items()
        for name, _, _ in sections(text)
        if not name.startswith('include ')
    }
    external_seen = set()
    backup_paths = {path for path in owned_paths if path.exists()}
    for path, text in files.items():
        if path in owned_paths:
            continue
        local_seen = set()
        conflicts = []
        for name, start, end in sections(text):
            if name.startswith('include '):
                continue
            if name in owned_sections or name in external_seen or name in local_seen:
                conflicts.append((start, end))
            else:
                local_seen.add(name)
        if conflicts:
            planned[path] = remove_section_ranges(text, conflicts)
            backup_paths.add(path)
        external_seen.update(local_seen)

    # Profile-owned sections take precedence over old Fluidd/client macros and
    # any other included definitions. Preserve each affected source as *.cfg.backup.
    files = load_configs(config, planned)
    seen = {}
    critical_sections = {'display', 'mcu'}
    for path, text in files.items():
        for name, _, _ in sections(text):
            if name.startswith('include '):
                continue
            if name in seen and (name in critical_sections or name.startswith('board_pins')):
                raise ValueError('Профиль ' + model + ' содержит повторную секцию [' + name +
                                 '] в ' + str(seen[name]) + ' и ' + str(path))
            if name.startswith('gcode_macro ') and name in seen:
                raise ValueError('Макрос [' + name + '] уже подключён из ' + str(seen[name]))
            seen.setdefault(name, path)
    return InstallPlan(planned, backup_paths=backup_paths)


def install_x_profile(config, serial, gcodes, payload):
    """Backward-compatible wrapper for the previous setup.py API."""
    return install_profile(config, serial, gcodes, payload, 'X')

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
    p.add_argument('--printer-model', choices=['X','XL'], help='Ручной выбор/подтверждение модели')
    p.add_argument('--skip-autodetect', action='store_true', help='Не прошивать AutoDetect (только для ручной установки)')
    p.add_argument('--nozzle-count', choices=['single','dual'], help='Число сопел; dual пока сохраняет текущий printer.cfg')
    config_group = p.add_mutually_exclusive_group()
    config_group.add_argument('--install-profile', action='store_true', help='Установить профиль выбранной модели')
    config_group.add_argument('--install-x-config', dest='install_profile', action='store_true', help=argparse.SUPPRESS)
    config_group.add_argument('--keep-config', action='store_true', help='Оставить текущий printer.cfg и обновить только MCU/панель')
    p.add_argument('--klipper', type=Path, default=Path.home() / 'klipper')
    p.add_argument('--config', type=Path, default=Path.home() / 'printer_data/config/printer.cfg')
    p.add_argument('--socket', type=Path, default=Path.home() / 'printer_data/comms/klippy.sock')
    p.add_argument('--service', default='klipper')
    p.add_argument('--check', action='store_true', help='Проверить комплект и выбранный профиль без прошивки/изменений')
    a = p.parse_args()
    if os.geteuid() == 0:
        raise ValueError('Запускайте от пользователя pi без sudo; sudo будет вызван для нужных операций.')
    if a.install_profile and a.keep_config:
        raise ValueError('--install-profile и --keep-config взаимоисключающие')
    if a.nozzle_count == 'dual' and a.install_profile:
        raise ValueError('Для двух сопел отдельный профиль ещё не готов; используйте --keep-config')
    try:
        detected_model = Path('/proc/device-tree/model').read_text().rstrip('\x00')
    except OSError:
        detected_model = ''
    boards = {
        'pi3':'Raspberry Pi 3 (GPIO11 SWCLK, GPIO8 SWDIO)',
        'pi4':'Raspberry Pi 4 (GPIO11 SWCLK, GPIO8 SWDIO)',
        'pi5':'Raspberry Pi 5 (RP1 GPIO11 SWCLK, GPIO8 SWDIO)',
        'opi3lts':'Orange Pi 3 LTS (GPIO profile not validated)',
        'opi5':'Orange Pi 5 (GPIO profile not validated)',
        'opi5plus':'Orange Pi 5 Plus (GPIO profile not validated)',
    }
    board_options = [
        ('1', 'Raspberry Pi 3'), ('2', 'Raspberry Pi 4'), ('3', 'Raspberry Pi 5'),
        ('4', 'Orange Pi 3 LTS'), ('5', 'Orange Pi 5'), ('6', 'Orange Pi 5 Plus'),
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
        print('Для Orange Pi пока нет проверенного профиля OpenOCD; прошивка и конфиги не изменены.')
        raise ValueError('SWD пока поддержан только на Raspberry Pi 3, 4 и 5')
    print('Подключение SWD (питание выключено): Raspberry pin 23 / GPIO11 -> PA14/SWCLK;')
    print('Raspberry pin 24 / GPIO8 -> PA13/SWDIO; pin 20 -> GND. VCC не подключать.')

    payload = Path(__file__).resolve().parents[1]
    autodetect_b64 = payload / 'firmware/autodetect/autodetect.bin.b64'
    if not autodetect_b64.is_file():
        raise ValueError('AutoDetect v0.6.0 отсутствует или не прошёл проверку SHA256')
    autodetect_image = base64.b64decode(autodetect_b64.read_bytes())
    if hashlib.sha256(autodetect_image).hexdigest() != AUTODETECT_SHA:
        raise ValueError('AutoDetect v0.6.0 отсутствует или не прошёл проверку SHA256')
    firmware_by_model = {
        'X': payload / 'firmware/designer_x/klipper.bin.b64',
        'XL': payload / 'firmware/designer_xl/klipper.bin.b64',
    }
    for model, image in firmware_by_model.items():
        if not image.is_file():
            raise ValueError('Klipper firmware для Designer ' + model + ' отсутствует')
        try:
            image_data = base64.b64decode(image.read_bytes())
        except ValueError:
            raise ValueError('Klipper firmware для Designer ' + model + ' повреждён')
        if hashlib.sha256(image_data).hexdigest() != FIRMWARE_SHA_BY_MODEL[model]:
            raise ValueError('Klipper firmware для Designer ' + model + ' отсутствует или SHA256 не совпадает')

    candidates = sorted(glob.glob('/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_*-if00-port0'))
    if a.serial:
        serial = a.serial
    elif len(candidates) == 1:
        serial = candidates[0]
    else:
        raise ValueError('Нужен ровно один FT232R; укажите --serial /dev/serial/by-id/...')
    if not serial.startswith('/dev/serial/by-id/') or not Path(serial).exists() or any(c.isspace() for c in serial):
        raise ValueError('Некорректный или отсутствующий serial-порт')
    if a.skip_autodetect and not a.printer_model:
        raise ValueError('--skip-autodetect требует явный --printer-model X|XL')
    if a.check and not a.printer_model:
        raise ValueError('--check требует явный --printer-model X|XL; аппаратный AutoDetect не запускается')
    if not a.check and not a.skip_autodetect and not sys.stdin.isatty():
        raise ValueError('AutoDetect требует интерактивное подтверждение отключённых моторов/нагревателей и измерения PE14')

    if not re.fullmatch(r'[\w@.-]+', a.service):
        raise ValueError('Некорректное имя сервиса')
    cmd = run(['systemctl', 'show', a.service, '-p', 'ExecStart', '--value'], capture_output=True, text=True).stdout
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
    if glob.glob('/dev/spidev0.*'):
        raise ValueError('SPI0 включён. Отключите SPI в raspi-config и перезагрузите Raspberry.')
    if not (a.klipper / 'klippy/extras/display/display.py').is_file():
        raise ValueError('Не найден Klipper host-файл klippy/extras/display/display.py')
    if not (a.config.resolve().parent / 'fluidd.cfg').exists():
        raise ValueError('Не найден fluidd.cfg рядом с printer.cfg')

    gcodes = a.config.resolve().parent.parent / 'gcodes'
    # Validate all available profiles before stopping Klipper or writing the probe image.
    def current_config_plan():
        return plan_config(a.config, serial, gcodes)

    profile_plans = ({model: install_profile(a.config, serial, gcodes, payload, model)
                      for model in ('X', 'XL')} if not a.keep_config else {})
    static_plan = driver_plan(a.klipper, payload)
    static_plan.update(panel_bundle_plan(payload))
    if a.check:
        model = a.printer_model
        nozzle_count = a.nozzle_count or 'single'
        install_selected_profile = not a.keep_config and nozzle_count == 'single'
        plan = profile_plans[model] if install_selected_profile else current_config_plan()
        plan.update(static_plan)
        print('Проверка комплекта Malevich Installer', INSTALLER_VERSION)
        print('Принтер: Designer', model, '| сопел:', '2' if nozzle_count == 'dual' else '1')
        print('Конфигурация:', 'профиль модели + macros.cfg' if install_selected_profile else 'текущий printer.cfg сохраняется')
        print('Klipper SHA256:', FIRMWARE_SHA_BY_MODEL[model])
        print('Файлов в плане:', len(plan))
        if isinstance(plan, InstallPlan) and plan.backup_paths:
            print('Будут сохранены резервные копии конфигов:')
            for path in sorted(plan.backup_paths):
                print(' ', path, '->', cfg_backup_path(path))
        print('Проверка завершена; изменений нет.')
        return

    if not a.skip_autodetect and not ask_yes_no(
            'Перед AutoDetect отключены шаговые двигатели и нагреватели принтера? Это обязательно для диагностического сканирования.', False):
        raise ValueError('AutoDetect отменён до прошивки')

    was_active = subprocess.run(['systemctl', 'is-active', '--quiet', a.service]).returncode == 0
    if was_active:
        api_error = None
        status = None
        if not a.socket.exists():
            api_error = 'API-сокет отсутствует: ' + str(a.socket)
        else:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(3)
                    sock.connect(str(a.socket))
                    sock.sendall(b'{"id":1,"method":"objects/query","params":{"objects":{"print_stats":null,"idle_timeout":null}}}\x03')
                    data = b''
                    while b'\x03' not in data:
                        chunk = sock.recv(65536)
                        if not chunk:
                            raise ValueError('Klipper API закрыл соединение без ответа')
                        data += chunk
                    status = json.loads(data.split(b'\x03')[0]).get('result', {}).get('status', {})
                if 'print_stats' not in status or 'idle_timeout' not in status:
                    api_error = 'API не вернул состояние печати'
            except (OSError, ValueError) as exc:
                api_error = str(exc)
        if api_error:
            print('Предупреждение: не удалось проверить состояние печати через Klipper API:', api_error)
            if not ask_yes_no(
                    'Печать точно остановлена, движения нет, двигатели и нагреватели отключены? Продолжить без проверки API?', False):
                raise ValueError('Установка отменена: состояние печати не подтверждено')
        elif (status.get('print_stats', {}).get('state') in ('printing', 'paused')
              or status.get('idle_timeout', {}).get('state') == 'Printing'):
            raise ValueError('Сначала завершите печать/движение; установка остановлена')
    else:
        print('Сервис Klipper не активен; проверка состояния через устаревший API-сокет пропущена.')

    if a.skip_autodetect:
        detected_printer = None
        printer_model = a.printer_model
    else:
        detected_printer = None
        printer_model = None

    print('LCD USB: PB14/PB15; этот комплект пока не содержит USB Host/MSC и передачи файлов на Raspberry Pi.')
    print('Установщик:', INSTALLER_VERSION)

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
    swd_cfg = SWD_PI5 if board == 'pi5' else SWD_NATIVE
    (backup / 'stm32-swd.cfg').write_text(swd_cfg)
    (backup / 'restore.py').write_text((payload / 'installer/restore.py').read_text())
    (backup / 'autodetect.bin').write_bytes(autodetect_image)
    firmware_stage = 'none'
    try:
        run(['sudo', 'systemctl', 'stop', a.service])
        with (backup / 'openocd.log').open('w') as log:
            probe = ('init; halt; '
                     'set id [mrw 0xe0042000]; '
                     'if {($id & 0xfff) != 0x413} {error "Not STM32F407/405"}; '
                     'set fs [mrh 0x1fff7a22]; '
                     'if {$fs != 512} {error "Expected 512 KiB flash"}; '
                     'dump_image previous.bin 0x08000000 0x80000; reset run; shutdown')
            run(['sudo','openocd','-f','stm32-swd.cfg','-c',probe], cwd=backup, stdout=log, stderr=subprocess.STDOUT)
        if (backup / 'previous.bin').stat().st_size != 524288:
            raise ValueError('Неполная резервная копия flash')

        if not a.skip_autodetect:
            firmware_stage = 'autodetect'
            with (backup / 'openocd.log').open('a') as log:
                run(['sudo','openocd','-f','stm32-swd.cfg','-c',
                     'program autodetect.bin verify reset exit 0x08000000'],
                    cwd=backup, stdout=log, stderr=subprocess.STDOUT)
            print('AutoDetect v0.6.0 прошит. На serial появится отчёт X/XL.', flush=True)
            detected_printer = scan_printer(
                serial, confirm_voltage=lambda prompt: input(color(prompt, '93')))
            print('AutoDetect определил Designer', detected_printer)
            if sys.stdin.isatty():
                selection = ask_choice('Подтвердите модель принтера:', [
                    ('1', 'Designer X'), ('2', 'Designer XL'),
                ], '1' if detected_printer == 'X' else '2')
                printer_model = {'1':'X', '2':'XL'}.get(selection)
            else:
                printer_model = a.printer_model or detected_printer
            if printer_model not in ('X','XL'):
                raise ValueError('Модель принтера не выбрана')
            if printer_model != detected_printer:
                print('Предупреждение: вручную выбрана версия, отличная от AutoDetect.')
                if not sys.stdin.isatty() or input(color("Чтобы продолжить, введите модель вручную ещё раз (X/XL): ", '93')).strip().upper() != printer_model:
                    raise ValueError('Ручное переопределение AutoDetect не подтверждено')
        else:
            printer_model = a.printer_model
            print('AutoDetect пропущен по --skip-autodetect; модель выбрана вручную: Designer', printer_model)

        nozzle_count = a.nozzle_count
        if not nozzle_count and sys.stdin.isatty():
            nozzle_count = {'1':'single','2':'dual'}.get(ask_choice('Сколько сопел у принтера?', [
                ('1', 'Одно сопло'), ('2', 'Два сопла (пока сохраняю текущий printer.cfg)'),
            ], '1'), 'single')
        nozzle_count = nozzle_count or 'single'

        if not a.nozzle_count and not sys.stdin.isatty():
            nozzle_count = 'single'
        install_selected_profile = not a.keep_config and nozzle_count == 'single'
        if nozzle_count == 'dual':
            print('Для двух сопел готового профиля пока нет: текущие оси, нагреватели и макросы будут сохранены.')
        elif a.keep_config:
            install_selected_profile = False
        elif not a.install_profile and sys.stdin.isatty():
            install_selected_profile = ask_yes_no(
                'Установить профиль Designer ' + printer_model + ' (printer.cfg, board_pins.cfg, macros.cfg)?', True)
        if printer_model == 'XL' and install_selected_profile and not a.check:
            print('XL-профиль включает select_pins на PC3. В исходном XL-файле 4 Z-адреса, а AutoDetect v0.6 проверяет 3 адреса второго банка.')
            if not ask_yes_no('Продолжить с этим проверочным XL-профилем и сверить результат после перезапуска?', False):
                install_selected_profile = False
                print('XL-конфиг сохранён без замены; установятся прошивка и панель.')

        firmware = base64.b64decode(firmware_by_model[printer_model].read_bytes())
        if hashlib.sha256(firmware).hexdigest() != FIRMWARE_SHA_BY_MODEL[printer_model]:
            raise ValueError('Контрольная сумма BIN не совпала')
        selected_plan = (profile_plans[printer_model] if install_selected_profile
                         else current_config_plan())
        cfg_backup_paths = (selected_plan.backup_paths
                            if isinstance(selected_plan, InstallPlan) else set())
        cfg_backup_moves = {
            path: cfg_backup_path(path)
            for path in cfg_backup_paths
            if path.exists()
        }
        planned = dict(selected_plan)
        planned.update(static_plan)
        print('Принтер: Designer', printer_model, '| AutoDetect:', detected_printer or 'пропущен',
              '| сопел:', '2' if nozzle_count == 'dual' else '1')
        print('Klipper BIN SHA256:', FIRMWARE_SHA_BY_MODEL[printer_model])
        print('Конфигурация:', 'профиль модели + отдельный macros.cfg' if install_selected_profile else 'текущий printer.cfg сохраняется')
        print('Панель: полный комплект устанавливается в', Path.home() / 'panel')
        print('USB накопитель LCD: линии PB14/PB15 известны, стек host/MSC не включён')
        if cfg_backup_moves:
            print('Перед заменой конфиги будут сохранены рядом:')
            for path, backup_path in sorted(cfg_backup_moves.items()):
                print(' ', path, '->', backup_path)
            print('Конфликтующие секции из подключённых файлов будут удалены из активных копий; версии профиля останутся активными.')

        manifest = {}
        for i, path in enumerate(planned):
            key = 'file-' + str(i)
            manifest[str(path)] = key if path.exists() else None
            if path.exists():
                shutil.copy2(path, backup / key)
        (backup / 'files.json').write_text(json.dumps(manifest, indent=2))
        (backup / 'new.bin').write_bytes(firmware)
        (backup / 'selection.json').write_text(json.dumps({
            'detected_model': detected_printer,
            'selected_model': printer_model,
            'nozzle_count': nozzle_count,
            'profile_installed': install_selected_profile,
            'installer_version': INSTALLER_VERSION,
        }, indent=2))
        print('Резервные копии и журнал:', backup, flush=True)

        firmware_stage = 'final'
        with (backup / 'openocd.log').open('a') as log:
            run(['sudo','openocd','-f','stm32-swd.cfg','-c',
                 'program new.bin verify reset exit 0x08000000'],
                cwd=backup, stdout=log, stderr=subprocess.STDOUT)
        for path, backup_path in cfg_backup_moves.items():
            if not path.exists():
                raise ValueError('Исходный конфиг исчез до сохранения: ' + str(path))
            os.replace(path, backup_path)
            print('Сохранена копия конфига:', backup_path)
        for path, text in planned.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.name + '.malevich-new')
            temp.write_text(text)
            if path.exists():
                shutil.copymode(path, temp)
            elif path in cfg_backup_moves and cfg_backup_moves[path].exists():
                shutil.copymode(cfg_backup_moves[path], temp)
            os.replace(temp, path)
        gcodes.mkdir(parents=True, exist_ok=True)
        run(['sudo','systemctl','start',a.service])
        ready(a.socket)
        print('ГОТОВО: Klipper ready. В Fluidd проверьте HC_PANEL_STATUS.')
        print('Откат: python3', backup / 'restore.py', '--service', a.service)
    except BaseException:
        if firmware_stage == 'autodetect':
            # Do not leave the diagnostic image installed if detection is cancelled
            # or returns UNKNOWN. Restore the exact pre-install flash backup.
            try:
                subprocess.run(['sudo','systemctl','stop',a.service], check=False)
                subprocess.run(['sudo','openocd','-f',str(backup/'stm32-swd.cfg'),'-c',
                                'program previous.bin verify reset exit 0x08000000'],
                               cwd=backup, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                if was_active:
                    subprocess.run(['sudo','systemctl','start',a.service], check=True)
                print('Исходная прошивка восстановлена; диагностика:', backup / 'openocd.log', file=sys.stderr)
            except (OSError, subprocess.CalledProcessError):
                print('Не удалось восстановить старую прошивку автоматически. Klipper оставлен остановленным; откат:',
                      backup / 'restore.py', file=sys.stderr)
        elif firmware_stage == 'final':
            subprocess.run(['sudo','systemctl','stop',a.service])
            print('Установка не завершена; Klipper остановлен. Откат:', backup / 'restore.py', file=sys.stderr)
        elif was_active:
            subprocess.run(['sudo','systemctl','start',a.service])
        print('Диагностика:', backup / 'openocd.log', file=sys.stderr)
        raise

if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit('Ошибка: ' + str(exc))
