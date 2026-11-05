#!/usr/bin/env bash
# Install the matched Malevich firmware/host bundle on Raspberry Pi 4.
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
base="https://raw.githubusercontent.com/CyrilVG/malevich_mode/a6a3e03b9639c960bdb1369f42c35159337f5c73"
mkdir -p "$work/installer" "$work/panel/host"
echo 'Загружаю проверенный комплект Malevich…'
wget --https-only --timeout=30 --tries=3 -qO "$work/installer/setup.py" "$base/installer/setup.py"
wget --https-only --timeout=30 --tries=3 -qO "$work/installer/restore.py" "$base/installer/restore.py"
wget --https-only --timeout=30 --tries=3 -qO "$work/installer/firmware.bin.b64" "$base/installer/firmware.bin.b64"
wget --https-only --timeout=30 --tries=3 -qO "$work/panel/host/malevich_panel.py" "$base/panel/host/malevich_panel.py"
(
    cd "$work"
    sha256sum -c <<'CHECKSUMS'
09df7175467a7cfaae71eb25c7c4ab7f82673b391fceff1bdfff89213f51ac05  installer/setup.py
e8d09934aa45e5038d5b73821ebfcb6112376663e638cccc206acc3c92e386cc  installer/restore.py
daf5d90eaa375f30f17d5bdbf696514cb50500c30df3824f50fc905f264d3546  installer/firmware.bin.b64
599e4c985bbed92d46dbca3ff91892d68534fa0263f52c99cf8a3ba0c7b4e36b  panel/host/malevich_panel.py
CHECKSUMS
)
python3 "$work/installer/setup.py" "$@"
