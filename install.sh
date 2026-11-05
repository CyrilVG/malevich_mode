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
mkdir -p "$work/installer" "$work/profiles/designer_x"
echo 'Загружаю проверенный комплект Malevich…'
wget --https-only --timeout=30 --tries=3 -qO "$work/installer/setup.py" "$base/installer/setup.py"
wget --https-only --timeout=30 --tries=3 -qO "$work/installer/restore.py" "$base/installer/restore.py"
wget --https-only --timeout=30 --tries=3 -qO "$work/installer/firmware.bin.b64" "$base/installer/firmware.bin.b64"
panel_files=(
    README.md display.cfg install.py host/malevich_panel.py
    src/malevich_panel.c src/malevich_logo.h
    tests/test_host.py tests/test_panel.c
    tests/stubs/board/gpio.h tests/stubs/board/irq.h
    tests/stubs/board/misc.h tests/stubs/command.h tests/stubs/sched.h
)
for relative in "${panel_files[@]}"; do
    mkdir -p "$work/panel/$(dirname "$relative")"
    wget --https-only --timeout=30 --tries=3 -qO "$work/panel/$relative" "$base/panel/$relative"
done
wget --https-only --timeout=30 --tries=3 -qO "$work/profiles/designer_x/printer.cfg" "$base/profiles/designer_x/printer.cfg"
wget --https-only --timeout=30 --tries=3 -qO "$work/profiles/designer_x/board_pins.cfg" "$base/profiles/designer_x/board_pins.cfg"
(
    cd "$work"
    sha256sum -c <<'CHECKSUMS'
dd4244ba5b283fd94f4e640dbd8da5fc67cdf037b2e23cd1640d39afd8dd705c  installer/setup.py
e8d09934aa45e5038d5b73821ebfcb6112376663e638cccc206acc3c92e386cc  installer/restore.py
daf5d90eaa375f30f17d5bdbf696514cb50500c30df3824f50fc905f264d3546  installer/firmware.bin.b64
96b28629918f69b0cc3bdb6ca871e47ff7141d8c050e94cc760898b5592f73db  panel/README.md
0e27799af067e74c3a81be864b80a1124e66082e5d3c0f1702f308eb9126cf40  panel/display.cfg
3f27a53e0483ac3336248bd4e684def1a63d84499edc223be2a10d1f9f94eaba  panel/install.py
599e4c985bbed92d46dbca3ff91892d68534fa0263f52c99cf8a3ba0c7b4e36b  panel/host/malevich_panel.py
2c9f16a6caf2f36d5a644e12249cb9095ae28fd1a6a724234be6635291261063  panel/src/malevich_panel.c
eb97b18563f4c81835be425bb9baaf52662eb83871feba3adfad8a539622286a  panel/src/malevich_logo.h
a4944beb22dc6b650902bc6123d7ca6c68a7bae089b44e92778c32c4bcd10dd2  panel/tests/test_host.py
736cdb9bcabfe1b1140b9d29c5165871d66a1774f91b579e954fe8b59dc51465  panel/tests/test_panel.c
c370744a0b556ecca290164b5f842d12e90f03dda495898ae66c2511e54d29b8  panel/tests/stubs/board/gpio.h
18dace68c4598c1a45c882590d1d6d4402ce4eaea4e58f77559f5ef25716e919  panel/tests/stubs/board/irq.h
ca9da56c430be14685e8704a216d7ccf1e7fca15c7d1ca5682e6a7e63ab2370d  panel/tests/stubs/board/misc.h
c95f936ca2b503179828105bc4befc43674dde3087c1e16fee1312e27283e108  panel/tests/stubs/command.h
b0c5fc1075a218bc4ef4a5e56be4815e71216729f51e34751afc00e83fa3800c  panel/tests/stubs/sched.h
578c9a1f143d254d0742cf9cdf176016d83cb2b127aa651b7dbcbb5455f573ad  profiles/designer_x/printer.cfg
f7cfaa1c676f9101a5faaf6ebd53d8d31895cda262a184503612deea4b259f9c  profiles/designer_x/board_pins.cfg
CHECKSUMS
)
python3 "$work/installer/setup.py" "$@"
