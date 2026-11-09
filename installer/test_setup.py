import importlib.util
import base64
import io
import hashlib
import os
import pty
import select
import threading
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('setup', Path(__file__).with_name('setup.py'))
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)

class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cfg = self.root / 'printer.cfg'
    def tearDown(self):
        self.temp.cleanup()
    def plan(self):
        return s.plan_config(self.cfg, '/dev/serial/by-id/test', self.root/'gcodes')
    def test_clean_and_idempotent(self):
        first = self.plan()
        self.assertIn('kinematics: none', first[self.cfg])
        self.assertIn('encoder_steps_per_detent: 4', first[self.cfg])
        for p,t in first.items():p.write_text(t)
        self.assertEqual(first,self.plan())
    def test_includes_preserve_motion_menu_and_footer(self):
        self.cfg.write_text('[include panel.cfg]\n[printer]\nkinematics: cartesian\n[stepper_x]\nstep_pin: PA1\n#*# SAVE_CONFIG\n#*# z_offset = 1.23\n')
        child = self.root/'panel.cfg'
        child.write_text('[display]\nlcd_type: ssd1306\ncs_pin: PD5\n[mcu]\nserial: old\n[menu __main test]\nname: Test\n')
        result=self.plan()
        self.assertIn('kinematics: cartesian',result[self.cfg])
        self.assertIn('step_pin: PA1',result[self.cfg])
        self.assertTrue(result[self.cfg].endswith('#*# z_offset = 1.23\n'))
        self.assertIn('[menu __main test]\nname: Test',result[child])
        self.assertNotIn('cs_pin:',result[child])
        self.assertNotIn('[display]',result[self.cfg])
        for p,t in result.items():p.write_text(t)
        self.assertEqual(result,self.plan())
    def test_duplicate_and_cycle_rejected(self):
        self.cfg.write_text('[display]\n[display]\n')
        with self.assertRaises(ValueError): self.plan()
        self.cfg.write_text('[include printer.cfg]\n')
        with self.assertRaises(ValueError): self.plan()
    def test_mcu_options_preserved(self):
        self.cfg.write_text('[mcu]\nserial: old\nbaud: 115200\nrestart_method: arduino\nmax_stepper_error: 0.000025\n')
        out=self.plan()[self.cfg]
        self.assertEqual(out.count('serial:'),1)
        self.assertIn('max_stepper_error: 0.000025',out)
    def test_missing_include_rejected(self):
        self.cfg.write_text('[include absent.cfg]\n')
        with self.assertRaises(ValueError):self.plan()
    def test_old_virtual_pins_outside_display_rejected(self):
        self.cfg.write_text('[gcode_button test]\npin: hc165:click\n')
        with self.assertRaises(ValueError):self.plan()
    def test_model_profiles_split_macros_and_bank_select(self):
        payload = Path(__file__).resolve().parents[1]
        (self.root / 'fluidd.cfg').write_text('')
        for model in ('X', 'XL'):
            planned = s.install_profile(self.cfg, '/dev/serial/by-id/test',
                                        self.root/'gcodes', payload, model)
            self.assertIn(self.root/'macros.cfg', planned)
            self.assertIn('[include macros.cfg]', planned[self.cfg])
            self.assertNotRegex(planned[self.cfg], r'(?m)^\[gcode_macro ')
            self.assertIn('[gcode_macro ', planned[self.root/'macros.cfg'])
            if model == 'XL':
                self.assertIn(self.root/'xl_inputs.cfg', planned)
                self.assertIn('[include xl_inputs.cfg]', planned[self.cfg])
                self.assertIn('[malevich_xl_inputs]',
                              planned[self.root/'xl_inputs.cfg'])
            else:
                self.assertNotIn(self.root/'xl_inputs.cfg', planned)
                self.assertNotIn('[include xl_inputs.cfg]', planned[self.cfg])
        xl = (payload/'profiles/designer_xl/printer.cfg').read_text()
        self.assertEqual(xl.count('select_pins: PC3'), 3)
        self.assertEqual(xl.count('select_pins: !PC3'), 4)
        self.assertIn('@GCODE_PATH@', xl)
        for section in ('stepper_z1', 'stepper_z2', 'stepper_z3'):
            body = xl.split('[' + section + ']')[1].split('[')[0]
            self.assertNotIn('position_min:', body)
            self.assertNotIn('position_max:', body)
        klipper = self.root / 'klipper'
        xl_host = s.xl_inputs_host_plan(klipper, payload)
        self.assertIn(klipper/'klippy/extras/malevich_xl_inputs.py', xl_host)
    def test_firmware_hashes_and_detect_parse(self):
        payload = Path(__file__).resolve().parents[1]
        expected = {
            'firmware/designer_x/klipper.bin.b64': s.FIRMWARE_SHA_BY_MODEL['X'],
            'firmware/designer_xl/klipper.bin.b64': s.FIRMWARE_SHA_BY_MODEL['XL'],
            'firmware/autodetect/autodetect.bin.b64': s.AUTODETECT_SHA,
        }
        for relative, digest in expected.items():
            data = base64.b64decode((payload/relative).read_bytes())
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
        self.assertEqual(s.parse_model('BOARD: DESIGNER X / TMC2130 / SPI (CONFIRMED)'), 'X')
        self.assertEqual(s.parse_model('BOARD: DESIGNER XL / TMC2209 / UART (CONFIRMED)'), 'XL')
        self.assertIsNone(s.parse_model('BOARD: UNKNOWN (lack of reply does not identify board)'))
    def test_autodetect_serial_protocol_once(self):
        master, slave = pty.openpty()
        responses = {
            b'R': b'=== Malevich STM32F407 X/XL AutoDetect v0.6.0 ===\r\n',
            b'E': b'[POWER] PE14 HIGH\r\n',
            b'P': b'PASSIVE runs=1 PB10=1 B1 PC3=1 PB10=1 B0 PC3=0 PB10=1\r\n',
            b'A': b'ARMED. Y runs ONE X/XL autodetection\r\n',
            b'Y': b'BOARD: DESIGNER XL / TMC2209 / UART (CONFIRMED)\r\nNo additional active scans without power-cycle\r\n',
        }
        stop = threading.Event()
        def emulate():
            while not stop.is_set():
                ready, _, _ = select.select([master], [], [], 0.2)
                if not ready:
                    continue
                try:
                    data = os.read(master, 32)
                except OSError:
                    return
                for byte in data:
                    response = responses.get(bytes([byte]))
                    if response:
                        os.write(master, response)
                    if byte == ord('X'):
                        stop.set()
                        return
        thread = threading.Thread(target=emulate, daemon=True)
        thread.start()
        capture = io.BytesIO()
        stream = io.TextIOWrapper(capture, encoding='utf-8')
        try:
            with redirect_stdout(stream):
                model = s.scan_printer(os.ttyname(slave), confirm_voltage=lambda _prompt: 'y', timeout=3)
            self.assertEqual(model, 'XL')
        finally:
            stop.set()
            thread.join(1)
            os.close(master)
            os.close(slave)

if __name__=='__main__':unittest.main()
