# Malevich Mode — Designer XL analog input monitor.
# Diagnostic-only: DOES NOT provide a Z endstop, stop motors or protect heaters.
# Licensed under GPL-3.0-or-later.
from collections import deque


class MalevichXLInputs:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.adc_reference = config.getfloat('adc_reference', 3.3, above=0.)
        # Calibrated from 26.07 V (Fluke) at PA0 normalized ADC = 0.848107.
        self.supply_scale = config.getfloat('supply_scale', 30.739, above=0.)
        self.threshold_mv = config.getfloat('trigger_delta_mv', 50.,
                                            minval=1., maxval=1500.)
        self.direction = config.getchoice('trigger_direction',
                                          ['rising', 'falling', 'both'], 'rising')
        self.filter_samples = config.getint('filter_samples', 4,
                                             minval=1, maxval=32)
        self.report_interval = config.getfloat('report_interval', 0.020,
                                               minval=0.010, maxval=1.0)
        self.warn_below = config.getfloat('warn_below', 22.0, above=0.)
        self.warn_above = config.getfloat('warn_above', 28.0, above=0.)
        if self.warn_above <= self.warn_below:
            raise config.error('malevich_xl_inputs: warn_above must exceed warn_below')
        self.load_samples = deque(maxlen=self.filter_samples)
        self.load_raw = None
        self.load_filtered = None
        self.load_baseline = None
        self.load_delta_mv = None
        self.triggered = False
        self.supply_raw = None
        self.supply_voltage = None
        self.supply_state = 'NO_DATA'

        pins = self.printer.lookup_object('pins')
        self.load_adc = pins.setup_pin('adc', config.get('loadcell_pin', 'PB1'))
        self.supply_adc = pins.setup_pin('adc', config.get('supply_pin', 'PA0'))
        # Standard Klipper ADC polling is suitable for observation only.
        # The sampling and reports are NOT synchronous with stepper movement.
        for adc, callback in ((self.load_adc, self._on_load_sample),
                              (self.supply_adc, self._on_supply_sample)):
            adc.setup_adc_sample(self.report_interval, 0.001, 8,
                                 minval=0., maxval=1., range_check_count=0)
            adc.setup_adc_callback(callback)

        query_adc = self.printer.load_object(config, 'query_adc')
        query_adc.register_adc('xl_loadcell_pb1', self.load_adc)
        query_adc.register_adc('xl_supply_pa0', self.supply_adc)
        gcode = self.printer.lookup_object('gcode')
        gcode.register_command('MALEVICH_XL_STATUS', self.cmd_status,
                               desc='Report Designer XL load cell and supply voltage')
        gcode.register_command('MALEVICH_XL_TARE', self.cmd_tare,
                               desc='Zero Designer XL load cell (no load on nozzle)')
        gcode.register_command('MALEVICH_XL_SET_THRESHOLD', self.cmd_threshold,
                               desc='Set diagnostic load cell threshold in millivolts')

    def _on_load_sample(self, samples):
        for _, raw in samples:
            self.load_raw = raw
            self.load_samples.append(raw)
            if len(self.load_samples) != self.filter_samples:
                continue
            self.load_filtered = sum(self.load_samples) / self.filter_samples
            # One-time baseline on boot; manual tare refreshes it.
            # Never auto-follow baseline while a contact event may be active.
            if self.load_baseline is None:
                self.load_baseline = self.load_filtered
            self.load_delta_mv = ((self.load_filtered - self.load_baseline)
                                  * self.adc_reference * 1000.)
            delta = self.load_delta_mv
            self.triggered = (delta >= self.threshold_mv if self.direction == 'rising'
                              else delta <= -self.threshold_mv if self.direction == 'falling'
                              else abs(delta) >= self.threshold_mv)

    def _on_supply_sample(self, samples):
        for _, raw in samples:
            self.supply_raw = raw
            self.supply_voltage = raw * self.supply_scale
            if self.supply_voltage < self.warn_below:
                self.supply_state = 'LOW'
            elif self.supply_voltage > self.warn_above:
                self.supply_state = 'HIGH'
            else:
                self.supply_state = 'OK'

    def get_status(self, eventtime):
        load = (None if self.load_filtered is None else
                self.load_filtered * self.adc_reference)
        baseline = (None if self.load_baseline is None else
                    self.load_baseline * self.adc_reference)
        return {
            'loadcell_adc': self.load_raw,
            'loadcell_voltage': load,
            'baseline_voltage': baseline,
            'delta_mv': self.load_delta_mv,
            'threshold_mv': self.threshold_mv,
            'trigger_direction': self.direction,
            'triggered': self.triggered,
            'supply_adc': self.supply_raw,
            'supply_voltage': self.supply_voltage,
            'supply_state': self.supply_state,
            'supply_scale': self.supply_scale,
            'diagnostic_only': True,
        }

    def cmd_status(self, gcmd):
        s = self.get_status(0.)
        if s['loadcell_voltage'] is None or s['supply_voltage'] is None:
            gcmd.respond_info('XL inputs: waiting for ADC readings')
            return
        gcmd.respond_info(
            'XL PB1: %.5f V, baseline %.5f V, delta %+.1f mV, '
            'threshold %.1f mV, triggered=%d (diagnostic only)\n'
            'XL PA0: ADC %.6f, supply %.3f V, state=%s' % (
                s['loadcell_voltage'], s['baseline_voltage'], s['delta_mv'],
                s['threshold_mv'], bool(s['triggered']),
                s['supply_adc'], s['supply_voltage'], s['supply_state']))

    def cmd_tare(self, gcmd):
        if self.load_filtered is None:
            raise gcmd.error('XL load cell: no stable ADC reading yet')
        self.load_baseline = self.load_filtered
        self.load_delta_mv = 0.
        self.triggered = False
        gcmd.respond_info('XL PB1 tare: baseline %.5f V' %
                          (self.load_baseline * self.adc_reference))

    def cmd_threshold(self, gcmd):
        self.threshold_mv = gcmd.get_float('MV', minval=1., maxval=1500.)
        # Recompute event status on the next ADC callback.
        gcmd.respond_info('XL diagnostic threshold: %.1f mV' % self.threshold_mv)


def load_config(config):
    return MalevichXLInputs(config)
