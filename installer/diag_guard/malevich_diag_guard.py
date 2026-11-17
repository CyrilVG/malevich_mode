# Malevich DIAG Guard v0.2.0-rc1
# Copyright (C) 2026 Malevich community contributors
# Distributed under GNU GPLv3 or any later version.
"""Pre-enable and guard configured X/Y/E TMC2209 DIAG during sensorless X/Y homing.

No direct writes to TMC fields are performed. This module deliberately does
not change the STM32 firmware, Z probe, motor currents or kinematic limits.
"""
import logging


class MalevichDiagGuard:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.preenable = config.getboolean('preenable', True)
        self.preenable_ms = config.getint('preenable_ms', 350, minval=0, maxval=5000)
        self.prearm_settle_ms = config.getint('prearm_settle_ms', 350,
                                             minval=0, maxval=5000)
        self.idle_samples = config.getint('idle_samples', 5, minval=1, maxval=30)
        self.idle_interval_ms = config.getint('idle_interval_ms', 20,
                                              minval=1, maxval=500)
        self.sample_time_us = config.getint('sample_time_us', 100,
                                            minval=1, maxval=1000)
        self.sample_count = config.getint('sample_count', 8, minval=1, maxval=32)
        self.min_travel_mm = config.getfloat('min_travel_mm', .50,
                                             minval=0., maxval=10.)
        # Never use self.stats: Klipper regards that name as a callable callback.
        self.diag_stats = {'passes': 0, 'blocks': 0, 'transients': 0,
                           'short_moves': 0}
        self._active_axis = None
        self._prepped_axis = None
        self.printer.register_event_handler('homing:home_rails_begin',
                                             self._home_rails_begin)
        self.printer.register_event_handler('homing:home_rails_end',
                                             self._home_rails_end)
        gcode = self.printer.lookup_object('gcode')
        gcode.register_command('MALEVICH_DIAG_GUARD_STATUS', self.cmd_status,
                               desc='Show Malevich DIAG Guard counters')
        # Keep the previous command as a compatibility alias.
        gcode.register_command('XL_DIAG_GUARD_STATUS', self.cmd_status,
                               desc='Compatibility alias for DIAG Guard status')
        self.printer.register_event_handler('klippy:ready', self._ready)

    @staticmethod
    def _axis(rails):
        axes = [r.get_name() for r in rails]
        if axes == ['stepper_x']:
            return 'x'
        if axes == ['stepper_y']:
            return 'y'
        return None

    def _ready(self):
        # Fail closed if the required objects are absent. This also makes the
        # target model explicit: 3 UART-readable TMC2209 drivers for X/Y/E.
        for stepper in ('stepper_x', 'stepper_y', 'extruder'):
            if self.printer.lookup_object('tmc2209 ' + stepper, None) is None:
                raise self.printer.config_error(
                    'MALEVICH DIAG GUARD requires [tmc2209 %s]' % stepper)
            en = self.printer.lookup_object('stepper_enable')
            en.lookup_enable(stepper)

    def _home_rails_begin(self, homing_state, rails):
        axis = self._axis(rails)
        if axis is None:
            return
        self._prepped_axis = None
        self._active_axis = axis
        toolhead = self.printer.lookup_object('toolhead')
        if self.preenable:
            names = ['stepper_x', 'stepper_y', 'extruder']
            self.printer.lookup_object('stepper_enable').set_motors_enable(
                names, True)
            if self.preenable_ms:
                toolhead.dwell(self.preenable_ms / 1000.)
            # Wait for asynchronous enable/TMC writes before reading CHOPCONF.
            toolhead.wait_moves()
        for name in ('stepper_x', 'stepper_y', 'extruder'):
            driver = self.printer.lookup_object('tmc2209 ' + name)
            try:
                chopconf = driver.mcu_tmc.get_register('CHOPCONF')
            except Exception as e:
                self._block('UART CHOPCONF read failed on %s: %s' % (name, e))
            if (chopconf & 0x0f) == 0:
                self._block('%s CHOPCONF.TOFF=0 (driver disabled)' % name)
        self._prepped_axis = axis
        logging.info('MALEVICH DIAG GUARD %s: X/Y/E enabled; CHOPCONF.TOFF nonzero',
                     axis.upper())

    def before_homing_move(self, hmove):
        axis = self._axis_from_move(hmove)
        if axis is None:
            return
        if self._prepped_axis != axis:
            self._block('%s pre-enable check did not complete' % axis.upper())
        # Called *after* Klipper's homing:homing_move_begin event; TMC virtual
        # endstop has armed StallGuard by this point. No move has started yet.
        toolhead = hmove.toolhead
        if self.prearm_settle_ms:
            toolhead.dwell(self.prearm_settle_ms / 1000.)
        toolhead.wait_moves()
        # Require idle DIAG for consecutive samples. A pre-active shared DIAG
        # line must not be interpreted as reaching the mechanical endstop.
        mcu_endstop = self._endstop(hmove, axis)
        for idx in range(self.idle_samples):
            print_time = toolhead.get_last_move_time()
            try:
                high = bool(mcu_endstop.query_endstop(print_time))
            except Exception as e:
                self._block('%s DIAG query failed: %s' % (axis.upper(), e))
            if high:
                self.diag_stats['transients'] += 1
                self._block('%s DIAG active before movement (sample %d/%d)'
                            % (axis.upper(), idx + 1, self.idle_samples))
            if idx + 1 < self.idle_samples:
                # A reactor pause lets the MCU update input state; it does
                # not issue a motion command and does not change coordinates.
                reactor = self.printer.get_reactor()
                reactor.pause(reactor.monotonic()
                              + self.idle_interval_ms / 1000.)

    def sample_parameters(self, hmove, default_time, default_count):
        if self._axis_from_move(hmove) is not None:
            return self.sample_time_us / 1000000., self.sample_count
        return default_time, default_count

    def after_homing_move(self, hmove):
        axis = self._axis_from_move(hmove)
        if axis is None or not self.min_travel_mm:
            return
        # CoreXY X or Y drives both rails. Stepper trigger delta times step
        # distance is the corresponding X/Y displacement magnitude (mm).
        traveled = [abs(sp.trig_pos - sp.start_pos)
                    * sp.stepper.get_step_dist()
                    for sp in hmove.stepper_positions
                    if sp.stepper_name in ('stepper_x', 'stepper_y')
                    and sp.trig_pos is not None]
        if not traveled:
            self._block('%s missing XY trigger positions' % axis.upper())
        distance = max(traveled)
        if distance < self.min_travel_mm:
            self.diag_stats['short_moves'] += 1
            self._block('%s triggered after %.3f mm (< %.3f mm)'
                        % (axis.upper(), distance, self.min_travel_mm))

    def _home_rails_end(self, homing_state, rails):
        axis = self._axis(rails)
        if axis is not None and axis == self._prepped_axis:
            self.diag_stats['passes'] += 1
            logging.info('MALEVICH DIAG GUARD %s: homing passed (%d)',
                         axis.upper(), self.diag_stats['passes'])
            self._prepped_axis = None
            self._active_axis = None

    @staticmethod
    def _axis_from_move(hmove):
        axes = {name.lower() for _endstop, name in hmove.endstops}
        return next(iter(axes)) if axes in ({'x'}, {'y'}) else None

    @staticmethod
    def _endstop(hmove, axis):
        for endstop, name in hmove.endstops:
            if name.lower() == axis:
                return endstop
        raise ValueError('No homing endstop for ' + axis)

    def _block(self, description):
        self.diag_stats['blocks'] += 1
        logging.error('MALEVICH DIAG GUARD: %s', description)
        raise self.printer.command_error('MALEVICH DIAG GUARD: ' + description)

    def get_status(self, eventtime):
        return dict(self.diag_stats)

    def cmd_status(self, gcmd):
        s = self.diag_stats
        gcmd.respond_info(
            'MALEVICH DIAG GUARD active: XYE preenable=%s/%dms; '
            'prearm settle=%dms, idle=%d samples, debounce=%dus x %d, '
            'minimum travel=%.2fmm; passes=%d blocks=%d '
            'transients=%d short_moves=%d' %
            (self.preenable, self.preenable_ms, self.prearm_settle_ms,
             self.idle_samples, self.sample_time_us, self.sample_count,
             self.min_travel_mm, s['passes'], s['blocks'],
             s['transients'], s['short_moves']))


def load_config(config):
    return MalevichDiagGuard(config)
