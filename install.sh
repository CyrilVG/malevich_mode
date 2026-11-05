#!/usr/bin/env bash
# Install the matched Malevich firmware/host bundle on Raspberry Pi 3/4/5.
set -euo pipefail
if [[ $EUID == 0 ]]; then
    echo 'Запустите от пользователя Klipper (pi), без sudo перед bash.' >&2
    exit 1
fi
command -v python3 >/dev/null
command -v wget >/dev/null
command -v sha256sum >/dev/null
work=$(mktemp -d "${TMPDIR:-/tmp}/malevich-install.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
base="https://raw.githubusercontent.com/CyrilVG/malevich_mode/main"
mkdir -p "$work/installer" "$work/panel/host" "$work/profiles/designer_x"
echo 'Загружаю проверенный комплект Malevich…'
wget --https-only --timeout=30 --tries=3 -qO "$work/installer/setup.py" "$base/installer/setup.py"
wget --https-only --timeout=30 --tries=3 -qO "$work/installer/restore.py" "$base/installer/restore.py"
wget --https-only --timeout=30 --tries=3 -qO "$work/installer/firmware.bin.b64" "$base/installer/firmware.bin.b64"
wget --https-only --timeout=30 --tries=3 -qO "$work/panel/host/malevich_panel.py" "$base/panel/host/malevich_panel.py"
wget --https-only --timeout=30 --tries=3 -qO "$work/profiles/designer_x/printer.cfg" "$base/profiles/designer_x/printer.cfg"
wget --https-only --timeout=30 --tries=3 -qO "$work/profiles/designer_x/board_pins.cfg" "$base/profiles/designer_x/board_pins.cfg"
(
    cd "$work"
    sha256sum -c <<'CHECKSUMS'
20acc07454308c49f2f3c7798af64c05d7c60f582bfcb345d1581a76b7ff4827  installer/setup.py
e8d09934aa45e5038d5b73821ebfcb6112376663e638cccc206acc3c92e386cc  installer/restore.py
daf5d90eaa375f30f17d5bdbf696514cb50500c30df3824f50fc905f264d3546  installer/firmware.bin.b64
599e4c985bbed92d46dbca3ff91892d68534fa0263f52c99cf8a3ba0c7b4e36b  panel/host/malevich_panel.py
578c9a1f143d254d0742cf9cdf176016d83cb2b127aa651b7dbcbb5455f573ad  profiles/designer_x/printer.cfg
f7cfaa1c676f9101a5faaf6ebd53d8d31895cda262a184503612deea4b259f9c  profiles/designer_x/board_pins.cfg
CHECKSUMS
)
python3 "$work/installer/setup.py" "$@"
