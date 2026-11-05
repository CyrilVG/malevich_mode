#!/usr/bin/env python3
"""Restore the matching complete MCU dump and host files from this directory."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--service', default='klipper')
a = p.parse_args()
b = Path(__file__).resolve().parent
manifest = json.loads((b / 'files.json').read_text())
assert (b / 'previous.bin').stat().st_size == 524288, 'Полный дамп отсутствует'
subprocess.run(['sudo', 'systemctl', 'stop', a.service], check=True)
subprocess.run(['sudo', 'openocd', '-f', 'stm32-swd.cfg', '-c',
                'program previous.bin verify reset exit 0x08000000'], cwd=b, check=True)
for name, saved in manifest.items():
    path = Path(name)
    if saved is None:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + '.malevich-restore')
        shutil.copy2(b / saved, temp)
        os.replace(temp, path)
subprocess.run(['sudo', 'systemctl', 'start', a.service], check=True)
print('Прежние прошивка и файлы восстановлены. Проверьте состояние Klipper.')
