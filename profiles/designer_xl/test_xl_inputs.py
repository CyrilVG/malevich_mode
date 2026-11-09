"""Unit checks for the diagnostic-only Designer XL ADC module."""
import importlib.util
from pathlib import Path
import unittest

source = Path(__file__).with_name('malevich_xl_inputs.py')
spec = importlib.util.spec_from_file_location('malevich_xl_inputs', source)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FakeADC:
    def setup_adc_sample(self, *args, **kwargs):
        self.sampling = args, kwargs

    def setup_adc_callback(self, callback):
        self.callback = callback

    def sample(self, value):
        self.callback([(0.1, value)])


class FakePins:
    def __init__(self):
        self.pins = {}

    def setup_pin(self, kind, pin):
        assert kind == 'adc'
        assert pin not in self.pins
        self.pins[pin] = FakeADC()
        return self.pins[pin]


class FakeGcode:
    def __init__(self):
        self.commands = {}

    def register_command(self, name, handler, desc=None):
        self.commands[name] = handler


class FakeQuery:
    def __init__(self):
        self.adc = {}

    def register_adc(self, name, obj):
        self.adc[name] = obj


class FakePrinter:
    def __init__(self):
        self.pins = FakePins()
        self.gcode = FakeGcode()
        self.query = FakeQuery()

    def lookup_object(self, name):
        return {'pins': self.pins, 'gcode': self.gcode}[name]

    def load_object(self, config, name):
        assert name == 'query_adc'
        return self.query


class FakeConfig:
    def __init__(self, **params):
        self.params = params
        self.printer = FakePrinter()

    def get_printer(self):
        return self.printer

    def get(self, name, default=None):
        return self.params.get(name, default)

    def getfloat(self, name, default=None, **kw):
        return float(self.params.get(name, default))

    def getint(self, name, default=None, **kw):
        return int(self.params.get(name, default))

    def getchoice(self, name, options, default=None):
        value = self.params.get(name, default)
        assert value in options
        return value

    def error(self, message):
        return ValueError(message)


class FakeCommand:
    error = ValueError

    def __init__(self, mv=None):
        self.mv = mv
        self.messages = []

    def respond_info(self, message):
        self.messages.append(message)

    def get_float(self, name, **kw):
        assert name == 'MV'
        return float(self.mv)


class XLInputsTest(unittest.TestCase):
    def test_adc_and_tare(self):
        cfg = FakeConfig()
        obj = mod.load_config(cfg)
        self.assertEqual(set(cfg.printer.pins.pins), {'PA0', 'PB1'})
        self.assertIn('xl_loadcell_pb1', cfg.printer.query.adc)
        self.assertIn('xl_supply_pa0', cfg.printer.query.adc)
        self.assertEqual(obj.get_status(0.)['supply_state'], 'NO_DATA')
        for _ in range(4):
            obj.load_adc.sample(0.515)
        obj.supply_adc.sample(0.848107)
        status = obj.get_status(0.)
        self.assertAlmostEqual(status['supply_voltage'], 26.07, places=2)
        self.assertFalse(status['triggered'])
        cmd = FakeCommand()
        obj.cmd_status(cmd)
        self.assertIn('XL PB1', cmd.messages[0])
        for _ in range(4):
            obj.load_adc.sample(0.81)
        self.assertTrue(obj.get_status(0.)['triggered'])
        obj.cmd_tare(FakeCommand())
        self.assertFalse(obj.get_status(0.)['triggered'])
        self.assertAlmostEqual(obj.get_status(0.)['delta_mv'], 0.)
        obj.cmd_threshold(FakeCommand(60))
        self.assertEqual(obj.get_status(0.)['threshold_mv'], 60.)
        self.assertTrue(obj.get_status(0.)['diagnostic_only'])

    def test_negative_load_and_voltage_warning(self):
        obj = mod.load_config(FakeConfig(trigger_direction='falling'))
        for _ in range(4):
            obj.load_adc.sample(0.52)
        for _ in range(4):
            obj.load_adc.sample(0.25)
        self.assertTrue(obj.get_status(0.)['triggered'])
        obj.supply_adc.sample(0.60)
        self.assertEqual(obj.get_status(0.)['supply_state'], 'LOW')
        obj.supply_adc.sample(0.96)
        self.assertEqual(obj.get_status(0.)['supply_state'], 'HIGH')
        obj.supply_adc.sample(0.848107)
        self.assertEqual(obj.get_status(0.)['supply_state'], 'OK')

    def test_invalid_voltage_window(self):
        with self.assertRaises(ValueError):
            mod.load_config(FakeConfig(warn_below=30., warn_above=28.))


if __name__ == '__main__':
    unittest.main()
