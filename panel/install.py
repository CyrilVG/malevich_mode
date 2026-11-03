#!/usr/bin/env python3
"""Install host integration without modifying the existing uc1701 driver."""
import argparse
from pathlib import Path
import shutil
import time
p = argparse.ArgumentParser()
p.add_argument('--klipper', type=Path, default=Path.home() / 'klipper')
a = p.parse_args()
root = Path(__file__).resolve().parent
folder = a.klipper / 'klippy/extras/display'
target = folder / 'display.py'
s = target.read_text()
needle = 'LCD_chips = {'
entry = "    'malevich_panel': malevich_panel.MalevichPanel,"
if entry not in s:
    if s.count(needle) != 1:
        raise SystemExit('Unsupported display.py; nothing changed')
    s = s.replace(needle, 'from . import malevich_panel\n\n' + needle + '\n' + entry, 1)
backup = folder / ('malevich-backup-' + str(time.time_ns()))
backup.mkdir()
shutil.copy2(target, backup / 'display.py')
module = folder / 'malevich_panel.py'
if module.exists():
    shutil.copy2(module, backup / module.name)
shutil.copy2(root / 'host/malevich_panel.py', module)
target.write_text(s)
print('Installed host driver. Backup:', backup)
print('Replace [display] using panel/display.cfg; matching MCU firmware required.')
