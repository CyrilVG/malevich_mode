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
mkdir -p "$work/installer" "$work/firmware/autodetect" \
    "$work/firmware/designer_x" "$work/firmware/designer_xl" \
    "$work/profiles/designer_x" "$work/profiles/designer_xl"
echo 'Загружаю проверенный комплект Malevich…'
wget --https-only --timeout=30 --tries=3 -qO "$work/installer/setup.py" "$base/installer/setup.py"
wget --https-only --timeout=30 --tries=3 -qO "$work/installer/restore.py" "$base/installer/restore.py"
wget --https-only --timeout=30 --tries=3 -qO "$work/installer/autodetect.py" "$base/installer/autodetect.py"
wget --https-only --timeout=30 --tries=3 -qO "$work/firmware/autodetect/autodetect.bin.b64" "$base/firmware/autodetect/autodetect.bin.b64"
wget --https-only --timeout=30 --tries=3 -qO "$work/firmware/designer_x/klipper.bin.b64" "$base/firmware/designer_x/klipper.bin.b64"
wget --https-only --timeout=30 --tries=3 -qO "$work/firmware/designer_xl/klipper.bin.b64" "$base/firmware/designer_xl/klipper.bin.b64"
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
wget --https-only --timeout=30 --tries=3 -qO "$work/profiles/designer_x/macros.cfg" "$base/profiles/designer_x/macros.cfg"
wget --https-only --timeout=30 --tries=3 -qO "$work/profiles/designer_xl/printer.cfg" "$base/profiles/designer_xl/printer.cfg"
wget --https-only --timeout=30 --tries=3 -qO "$work/profiles/designer_xl/board_pins.cfg" "$base/profiles/designer_xl/board_pins.cfg"
wget --https-only --timeout=30 --tries=3 -qO "$work/profiles/designer_xl/macros.cfg" "$base/profiles/designer_xl/macros.cfg"
(
    cd "$work"
    sha256sum -c <<'CHECKSUMS'
d50718da5361f86c70c7225e3aeeae8119179f5d0928a22f5b44d2f1811299ba  installer/setup.py
e8d09934aa45e5038d5b73821ebfcb6112376663e638cccc206acc3c92e386cc  installer/restore.py
6326e5d45220b6177c8a6d48cdfea1a7d7b65ad995d9af2b44480fac58da1657  installer/autodetect.py
a0d4a8e6ed22daac28582c19cbca850025ea0aa53981ab4b0ff4db91f1437299  firmware/autodetect/autodetect.bin.b64
59e2888bb4443caf92a5607551eb8e9cacecaa813eb6c57e42b4b4bd6857671f  firmware/designer_x/klipper.bin.b64
59e2888bb4443caf92a5607551eb8e9cacecaa813eb6c57e42b4b4bd6857671f  firmware/designer_xl/klipper.bin.b64
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
c4f51641fcd4df555611db054ba70ff429fc5daa8e365bf4d5473ef1a23fade7  profiles/designer_x/printer.cfg
a950e13753e4dd67864218a463479800f5247a1df84b47580150c8c474f77eae  profiles/designer_x/board_pins.cfg
f94a14b2baad3b2b51d73adb2a220979f58b17894931c88cd20994576ecc3dc5  profiles/designer_x/macros.cfg
e2f9ffb8f1a6d920483a1c25b38292c11cf06da288f621fea4c853d2fc57d5c8  profiles/designer_xl/printer.cfg
10dee91457082cc9b2ac92551f95c2f24811500d1c5b22a07a164671162c9b11  profiles/designer_xl/board_pins.cfg
a4f14ea3b9099179776b98fb125ef48f34aaea8e8aac4152d6cc5f1897c6a7b6  profiles/designer_xl/macros.cfg
CHECKSUMS
)
python3 "$work/installer/setup.py" "$@"
