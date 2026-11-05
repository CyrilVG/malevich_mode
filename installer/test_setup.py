import importlib.util
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

if __name__=='__main__':unittest.main()
