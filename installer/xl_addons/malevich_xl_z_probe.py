# XL_PREHOME_CLEAR_AND_PROBE_XY_FIX_V3
# XL_DUAL_STAGE_STANDARD_PROBE_V1
# XL_TWO_STAGE_Z_HOME_V1
# XL_SESSION_PARK_BEFORE_FIRST_POINT_V2
# XL_SESSION_TARE_200MV_V1
# PICASO Designer XL - PB1 analog MCU endstop + standard PROBE v0.4.0 (force-calibrated 1 kgf nominal).
# Uses Klipper's native MCU trigger_analog + trsync. No Raspberry Pi polling
# is used for stopping a homing move. Requires Klipper MCU firmware compiled
# with WANT_ADC and WANT_TRIGGER_ANALOG.
#
# PB1 strain gauge for Designer XL Z homing. Homing is opt-in via
# allow_homing; every attempt undergoes noise, baseline and motion checks.
# Manual one-shot arming can be enabled using arm_required: True.
# SPDX-License-Identifier: GPL-3.0-or-later

import collections
import json
import math
import os
from pathlib import Path
import statistics

from . import trigger_analog
from . import probe as klipper_probe

ADC_MAX = 4095


def mcu_lowpass_sections(rate_hz, cutoff_hz, stages=4):
    """SOS coefficients for cascaded stable one-pole IIR low-pass sections.

    Each section: H(z) = alpha / (1 - (1-alpha)*z^-1).
    Coefficients are interpreted by Klipper MCU sos_filter.c, not host.
    Four sections attenuate isolated ADC conversion spikes without needing
    SciPy; this stage does not authorize actual Z homing.
    """
    if not (0. < cutoff_hz < 0.25 * rate_hz):
        raise ValueError('cutoff must be between zero and sample_rate/4')
    if stages < 1 or stages > 8:
        raise ValueError('invalid SOS stage count')
    alpha = 1. - math.exp(-2. * math.pi * cutoff_hz / rate_hz)
    return [(alpha, 0., 0., 1., alpha - 1., 0.) for _ in range(stages)]


class AnalogPinSensor:
    """Adapt stock MCU_adc to the trigger_analog sensor interface."""
    def __init__(self, config, pin, rate_hz, callback):
        self.printer = config.get_printer()
        self._pins = self.printer.lookup_object('pins')
        self.adc = self._pins.setup_pin('adc', pin)
        self.mcu = self.adc.get_mcu()
        self.rate_hz = rate_hz
        # Single-sample events are delivered to MCU trigger_analog at rate_hz.
        # Serial reports are batched; serial round trip is NOT on stop path.
        self.adc.setup_adc_sample(1.0 / rate_hz, sample_count=1,
                                  batch_num=1)
        self.adc.setup_adc_callback(callback)
        self._trigger_analog_oid = None

    def get_mcu(self):
        return self.mcu

    def get_samples_per_second(self):
        return self.rate_hz

    def lookup_sensor_error(self, error_code):
        return 'PB1 ADC sensor-specific error %d' % error_code

    def setup_trigger_analog(self, trigger_analog_oid):
        # Called during Klipper MCU configuration build; the ADC OID must be
        # available from an earlier registered config callback.
        command = ('analog_in_attach_trigger_analog oid=%c '
                   'trigger_analog_oid=%c')
        if self.mcu.try_lookup_command(command) is None:
            raise self.printer.config_error(
                'Malevich XL Z: firmware lacks analog_in_attach_trigger_analog; '
                'rebuild Klipper MCU with WANT_TRIGGER_ANALOG')
        if self.adc._oid is None:
            raise self.printer.config_error(
                'Malevich XL Z: ADC configuration OID not allocated')
        # IMPORTANT: This is an init command. The trigger_analog object must
        # already have been configured before it can be attached to ADC.
        self.mcu.add_config_cmd(
            'analog_in_attach_trigger_analog oid=%d trigger_analog_oid=%d'
            % (self.adc._oid, trigger_analog_oid), is_init=True)


def _percentile_sorted(values, q):
    # Same linear percentile definition as MALEVICH_XL_ADC_STATS.
    index = (len(values) - 1) * q
    low = int(index)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (index - low)


def calculate_baseline(samples, sample_window_s=0.24,
                       min_samples=24, max_noise_fraction=0.015/3.3):
    """Return (median fractional ADC, p05-p95 noise fraction, latest_time).

    Ignore isolated ADC conversion outliers when measuring *stationary* noise.
    Do not use this host-side calculation to stop a motor; MCU trigger_analog
    is responsible for that. Its filtering must be independently validated.
    """
    if not samples:
        raise ValueError('no ADC samples')
    last_time = samples[-1][0]
    values = sorted(v for t, v in samples
                    if last_time - sample_window_s <= t <= last_time)
    if len(values) < min_samples:
        raise ValueError('insufficient ADC samples (%d/%d)' %
                         (len(values), min_samples))
    p05 = _percentile_sorted(values, 0.05)
    p95 = _percentile_sorted(values, 0.95)
    noise = p95 - p05
    if noise > max_noise_fraction:
        raise ValueError('ADC signal unstable (%.1f mV p05-p95)' %
                         (noise * 3300.0))
    return statistics.median(values), noise, last_time


class MalevichXLZProbe:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.reactor = self.printer.get_reactor()
        self.pin = config.get('sensor_pin', 'PB1')
        self.vref = config.getfloat('adc_vref', 3.3, above=2.5, below=3.7)
        self.rate_hz = config.getint('sample_rate', 250, minval=50, maxval=500)
        self.mcu_filter_hz = config.getfloat('mcu_filter_hz', 8.0,
                                              minval=3.0, maxval=20.0)
        if self.mcu_filter_hz >= 0.25 * self.rate_hz:
            raise config.error('MCU low-pass cutoff must be < sample_rate/4')
        self.threshold_mv = config.getfloat('threshold_mv', 1493., minval=10., maxval=2000.)
        self.max_noise_mv = config.getfloat('max_noise_mv', 15., minval=1., maxval=100.)
        # Allow host serial batching and callback scheduling jitter. This
        # affects stationary tare only, not the 250 Hz MCU stop path.
        self.tare_window_s = config.getfloat('tare_window_s', 1.0,
                                              minval=0.24, maxval=2.0)
        self.tare_wait_s = config.getfloat('tare_wait_s', 2.0,
                                            minval=0.2, maxval=5.0)
        self.reference_idle_v = config.getfloat('reference_idle_voltage', 1.770,
                                                 above=0.1, below=self.vref)
        self.max_idle_deviation_mv = config.getfloat('max_idle_deviation_mv', 80.,
                                                       minval=10., maxval=300.)
        # Safety: 500mV is a MANUAL, physically-confirmed rebase envelope.
        # Automatic pre-contact taring keeps the narrow guard above.
        self.manual_idle_limit_mv = config.getfloat('manual_idle_limit_mv', 500.,
                                                     minval=30., maxval=1000.)
        self._approved_idle_v = self.reference_idle_v
        self._last_tare_at = None
        # Opt-in off-glass tare. Current XY position must be homed and X<=0.
        # The most recent off-glass tare is consumed once by MCU trigger setup.
        self.require_park_tare = config.getboolean('require_park_tare', False)
        self.park_x = config.getfloat('park_x', -10., minval=-21., maxval=0.)
        self.park_x_max = config.getfloat('park_x_max', 0., maxval=0.)
        self.park_max_age_s = config.getfloat('park_max_age_s', 300., minval=1., maxval=600.)
        self.park_max_noise_mv = config.getfloat('park_max_noise_mv', 150., minval=1., maxval=500.)
        self.park_settle_s = config.getfloat('park_settle_s', 0.6, minval=0.3, maxval=5.)
        self.auto_park_probe = config.getboolean('auto_park_probe', False)
        self.park_safe_z = config.getfloat('park_safe_z', 5.0, minval=1., maxval=20.)
        self._park_tare = None  # (baseline fraction, noise mV, host monotonic)
        self.park_recheck_mv = config.getfloat('park_recheck_mv', 200., minval=10., maxval=500.)
        self._probe_session_park = None  # session baseline: valid for full multi-point run
        # Persist the LAST accepted unloaded parked baseline. Reject a new
        # tare if it differs by >500 mV. This is not a fixed OEM reference:
        # we continue to use the new zero for every accepted measurement.
        self.park_previous_limit_mv = config.getfloat(
            'park_previous_limit_mv', 500.0, minval=1., maxval=1000.)
        self._park_reference_file = (Path(self.printer.get_start_args()['config_file'])
                                     .resolve().parent / '.malevich_xl_park_reference.json')
        self._park_reference_v = None  # read after ADC raw range options
        # Limited homing (not standard G28.1 with a 927 mm search).
        self._limited_home_active = False
        self._two_stage_active = False
        self._two_stage_trigger_mv = None
        self.max_limited_home_mm = config.getfloat(
            'max_limited_home_mm', 2.0, above=0., maxval=5.0)
        self.limited_home_speed = config.getfloat(
            'limited_home_speed', 0.25, above=0., maxval=1.0)
        self.limited_home_retract_mm = config.getfloat(
            'limited_home_retract_mm', 2.0, above=0., maxval=5.0)
        self.raw_min_v = config.getfloat('raw_min_voltage', 0.20,
                                          minval=0., below=self.vref)
        self.raw_max_v = config.getfloat('raw_max_voltage', 3.27,
                                          above=self.raw_min_v, maxval=self.vref)
        self._park_reference_v = self._read_park_reference()
        self.allow_homing = config.getboolean('allow_homing', False)
        self.arm_seconds = config.getfloat('arm_seconds', 15., minval=2., maxval=60.)
        self.arm_required = config.getboolean('arm_required', True)
        # Explicit bounds for ordinary G28 homing. Negative Z homing in
        # corexy.py searches 1.5*(position_max-position_endstop), not just
        # position_max. Keep bounds independent of the stepper config.
        # Old config key names retained to support v0.1.6 configs.
        self.max_test_travel_mm = config.getfloat(
            'max_test_travel_mm', 8.0, above=0.)
        self.max_test_speed = config.getfloat(
            'max_test_speed', 1.0, above=0., maxval=10.)
        z_cfg = config.getsection('stepper_z')
        self._z_endstop = z_cfg.getfloat('position_endstop')
        self._z_min = z_cfg.getfloat('position_min', 0.)
        self._z_max = z_cfg.getfloat('position_max')
        self._z_homing_speed = z_cfg.getfloat('homing_speed', 5.0)
        self._z_homing_positive_dir = z_cfg.getboolean('homing_positive_dir', None)
        self._z_retract = z_cfg.getfloat('homing_retract_dist', 5.)
        # A separately gated standard Probe interface can reuse the MCU
        # trigger_analog endstop. Legacy G28 Z remains unchanged.
        self.enable_probe_bridge = config.getboolean('enable_probe_bridge', False)
        self.allow_probing = config.getboolean('allow_probing', False)
        self.max_probe_travel_mm = config.getfloat(
            'max_probe_travel_mm', 12., above=0., maxval=30.)
        self.max_probe_speed = config.getfloat(
            'max_probe_speed', 1.0, above=0., maxval=5.)
        self._probe_active = False
        self._probe_speed = None
        # Native Klipper probe sessions use this two-pass MCU stop.
        # PROBE_SPEED continues to control the *fine* pass.
        self.probe_two_stage = config.getboolean('probe_two_stage', True)
        self.probe_coarse_speed = config.getfloat(
            'probe_coarse_speed', 3.0, above=0., maxval=5.0)
        self.probe_coarse_threshold_mv = config.getfloat(
            'probe_coarse_threshold_mv', 200.0, minval=50., maxval=500.)
        self.probe_coarse_retract_mm = config.getfloat(
            'probe_coarse_retract_mm', 2.0, above=0., maxval=5.0)
        self.probe_coarse_travel_mm = config.getfloat(
            'probe_coarse_travel_mm', 5.0, above=0., maxval=10.)
        self.probe_fine_travel_mm = config.getfloat(
            'probe_fine_travel_mm', 4.0, above=0., maxval=10.)
        self._probe_coarse_phase = False
        self._probe_coarse_effective_mv = None
        if self.probe_two_stage and not (self.require_park_tare and self.auto_park_probe):
            raise config.error('XL PROBE two-stage requires off-glass session tare')
        if self.enable_probe_bridge and self.allow_probing:
            if self.max_idle_deviation_mv >= self.threshold_mv:
                raise config.error(
                    'XL PROBE: max_idle_deviation_mv must be below threshold_mv')
            if self.max_noise_mv * 2. >= self.threshold_mv:
                raise config.error(
                    'XL PROBE: max_noise_mv must be less than half threshold_mv')
        self._arm_expires = 0.
        self._home_prepared = False
        self.printer.register_event_handler(
            'homing:homing_move_begin', self._on_homing_move_begin)
        self.samples = collections.deque(maxlen=256)
        self.baseline_frac = None
        self._last_tare_noise = None
        self._adc = AnalogPinSensor(config, self.pin, self.rate_hz,
                                    self._adc_callback)
        self._mcu = self._adc.get_mcu()
        self._trigger = trigger_analog.MCU_trigger_analog(self._adc)
        # Real-time MCU-side IIR filter, evaluated for EVERY ADC sample BEFORE
        # trigger_analog checks its threshold. Host-side reporting, QUERY_ADC,
        # QUERY_ENDSTOPS and tare continue to observe unsmoothed ADC values.
        # Four first-order SOS sections at 8 Hz by default (250 Hz input).
        # The filter resets before each stationary test or homing attempt.
        self._mcu_filter_stages = 4
        filt = trigger_analog.MCU_SosFilter(
            self._mcu, self._trigger.get_dispatch().get_command_queue(),
            self._mcu_filter_stages)
        design = trigger_analog.DigitalFilter(self.rate_hz,
                                              self.printer.config_error)
        design.filter_sections.extend(mcu_lowpass_sections(
            self.rate_hz, self.mcu_filter_hz, self._mcu_filter_stages))
        filt.set_filter_design(design)
        self._trigger.setup_sos_filter(filt)
        ppins = self.printer.lookup_object('pins')
        ppins.register_chip('malevich_xl_z_probe', self)
        query_adc = self.printer.load_object(config, 'query_adc')
        query_adc.register_adc('xl_loadcell_pb1', self._adc.adc)

        self._supply_adc = None
        self._supply_fullscale = config.getfloat('supply_fullscale', 30.73,
                                                  above=1.)
        supply_pin = config.get('supply_pin', None)
        if supply_pin is not None:
            self._supply_adc = ppins.setup_pin('adc', supply_pin)
            self._supply_adc.setup_adc_sample(0.25, sample_time=0.001,
                                               sample_count=4)
            query_adc.register_adc('xl_supply_pa0', self._supply_adc)

        self.gcode.register_command('MALEVICH_XL_STATUS', self.cmd_status,
                                    desc='XL PB1 ADC and supply status')
        self.gcode.register_command('MALEVICH_XL_ADC_DEBUG', self.cmd_adc_debug,
                                    desc='XL PB1 ADC stream timing diagnostics')
        self.gcode.register_command('MALEVICH_XL_ADC_STATS', self.cmd_adc_stats,
                                    desc='XL PB1 ADC noise and outlier distribution')
        self.gcode.register_command('MALEVICH_XL_TARE', self.cmd_tare,
                                    desc='XL PB1 establish unloaded median baseline')
        self.gcode.register_command('XL_Z_ACCEPT_IDLE', self.cmd_accept_idle,
                                    desc='Manually approve stable unloaded PB1 baseline')
        self.gcode.register_command('XL_Z_IDLE_STATUS', self.cmd_idle_status,
                                    desc='Show approved and last tare baselines')
        self.gcode.register_command('XL_Z_PARK_TARE', self.cmd_park_tare,
                                    desc='Take a one-shot off-bed unloaded baseline')
        self.gcode.register_command('XL_Z_PARK_STATUS', self.cmd_park_status,
                                    desc='Show pending one-shot off-bed baseline')
        self.gcode.register_command('XL_Z_PARK_COMPARE', self.cmd_park_compare,
                                    desc='Compare present PB1 against parked zero without moving')
        self.gcode.register_command('XL_Z_PARK_REFERENCE', self.cmd_park_reference,
                                    desc='Show persisted last unloaded park zero')
        self.gcode.register_command('XL_Z_PARK_REFERENCE_RESET', self.cmd_park_reference_reset,
                                    desc='Explicitly reset persisted park reference after hardware inspection')
        self.gcode.register_command('XL_Z_HOME_LIMITED', self.cmd_home_limited,
                                    desc='MCU-triggered Z home with short operator-confirmed travel')
        self.gcode.register_command('XL_Z_HOME_TWO_STAGE', self.cmd_home_two_stage,
                                    desc='Fast +200mV MCU stop, retract, slow force-calibrated Z home')
        self.gcode.register_command('XL_Z_PREHOME_CLEAR', self.cmd_prehome_clear,
                                    desc='Lower XL bed before G28 even if Z unhomed')
        self.gcode.register_command('MALEVICH_XL_SET_THRESHOLD', self.cmd_threshold,
                                    desc='XL set PB1 contact threshold in mV')
        self.gcode.register_command('XL_Z_ARM', self.cmd_arm,
                                    desc='One-shot arm of experimental Z analog homing')
        self.gcode.register_command('XL_Z_TRIGGER_TEST', self.cmd_trigger_test,
                                    desc='Stationary MCU trsync test, never moves motors')
        self.gcode.register_command('XL_Z_FILTER_INFO', self.cmd_filter_info,
                                    desc='Report MCU SOS spike filter settings')
        self.gcode.register_command('XL_Z_TEST_BOUNDS', self.cmd_test_bounds,
                                    desc='Check experimental Z travel bounds without motion')
        # Do not register the standard probe until explicitly enabled. This
        # preserves the behavior of old configurations byte-for-byte otherwise.
        if self.enable_probe_bridge:
            self._probe_offsets = klipper_probe.ProbeOffsetsHelper(config)
            self._probe_params = klipper_probe.ProbeParameterHelper(config)
            self._probe_homing = klipper_probe.DescendToEndstopHelper(
                config, self, self._probe_offsets, self._probe_params)
            self._probe_session = klipper_probe.SampleAveragingHelper(
                config, self._probe_params, self._begin_probe_session)
            self._probe_cmd = klipper_probe.ProbeCommandHelper(
                config, self, self.query_endstop)
            self.printer.add_object('probe', self)

    def _adc_callback(self, samples):
        self.samples.extend(samples)

    def _value(self):
        if not self.samples:
            raise self.printer.command_error('XL PB1: no ADC data')
        sample_time, frac = self.samples[-1]
        now_pt = self._mcu.estimated_print_time(self.reactor.monotonic())
        if now_pt - sample_time > 0.50:
            raise self.printer.command_error('XL PB1 ADC data stale')
        return frac * self.vref

    def _read_stable_idle(self, max_noise_mv=None):
        # Collect fresh PB1 readings. Off-bed sampling uses its own relaxed
        # noise limit; sensor saturation and ADC freshness checks remain.
        deadline = self.reactor.monotonic() + self.tare_wait_s
        min_samples = max(12, self.rate_hz // 10)
        while True:
            try:
                avg, noise, last_time = calculate_baseline(
                    self.samples, sample_window_s=self.tare_window_s,
                    min_samples=min_samples,
                    max_noise_fraction=((self.max_noise_mv if max_noise_mv is None else max_noise_mv) / 1000. / self.vref))
            except ValueError as e:
                reason = str(e)
                if (reason == 'no ADC samples'
                    or reason.startswith('insufficient ADC samples')
                    or reason.startswith('ADC signal unstable')):
                    if self.reactor.monotonic() < deadline:
                        self.reactor.pause(min(self.reactor.monotonic() + 0.05,
                                               deadline))
                        continue
                raise self.printer.command_error('XL Z tare rejected: %s' % e)
            now_pt = self._mcu.estimated_print_time(self.reactor.monotonic())
            if now_pt - last_time > 0.50 or last_time > now_pt + 0.05:
                if self.reactor.monotonic() < deadline:
                    self.reactor.pause(min(self.reactor.monotonic() + 0.05,
                                           deadline))
                    continue
                raise self.printer.command_error('XL Z tare rejected: stale ADC')
            break
        avg_v = avg * self.vref
        if not (self.raw_min_v + 0.05 < avg_v < self.raw_max_v - 0.2):
            raise self.printer.command_error('XL Z tare rejected: sensor out of range')
        return avg, noise, last_time

    def _tare(self):
        # Invoked before *every* MCU-triggered G28/PROBE; do not cache a tare
        # for 3-5 min, as XY/PTFE load may change on the very next movement.
        # Compare against the fixed, previously approved unloaded reference,
        # NOT the last automatic tare (that could slowly absorb real contact).
        avg, noise, last_time = self._read_stable_idle()
        avg_v = avg * self.vref
        deviation_mv = (avg_v - self._approved_idle_v) * 1000.
        if abs(deviation_mv) > self.max_idle_deviation_mv:
            raise self.printer.command_error(
                'XL Z tare rejected: offset %+.1f mV from approved idle %.5f V '
                '(auto limit %.1f mV). If nozzle is PHYSICALLY CLEAR, '
                'use XL_Z_ACCEPT_IDLE CONFIRM=1 NOZZLE_CLEAR=1'
                % (deviation_mv, self._approved_idle_v,
                   self.max_idle_deviation_mv))
        self.baseline_frac = avg
        self._last_tare_noise = noise * self.vref * 1000.
        self._last_tare_at = self.reactor.monotonic()
        return avg_v

    def cmd_accept_idle(self, gcmd):
        # This operation can never independently prove that a nozzle is not
        # already touching the bed.  Require an explicit human confirmation.
        if (gcmd.get_int('CONFIRM', 0) != 1
            or gcmd.get_int('NOZZLE_CLEAR', 0) != 1):
            raise gcmd.error('Physical clearance required: '
                             'XL_Z_ACCEPT_IDLE CONFIRM=1 NOZZLE_CLEAR=1')
        if (self._probe_active or self._home_prepared
            or self._arm_expires > self.reactor.monotonic()):
            raise gcmd.error('XL Z idle approval refused while armed or probing')
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.wait_moves()
        begin_pt = self._mcu.estimated_print_time(self.reactor.monotonic())
        # Ensure the stationary window is newer than the last queued move.
        self.reactor.pause(self.reactor.monotonic() +
                           max(0.40, self.tare_window_s + 0.10))
        avg, noise, last_time = self._read_stable_idle()
        if last_time < begin_pt + self.tare_window_s:
            raise gcmd.error('XL Z idle approval rejected: no fresh ADC window')
        avg_v = avg * self.vref
        offset_mv = (avg_v - self.reference_idle_v) * 1000.
        if abs(offset_mv) > self.manual_idle_limit_mv:
            raise gcmd.error(
                'XL Z idle approval rejected: %+.1f mV from configured idle '
                '(manual envelope %.1f mV)' % (offset_mv,
                                               self.manual_idle_limit_mv))
        # Only approved here, in RAM, after physically checking nozzle clearance.
        # A Klipper restart discards this reference; no SAVE_CONFIG occurs.
        self._approved_idle_v = avg_v
        self.baseline_frac = avg
        self._last_tare_noise = noise * self.vref * 1000.
        self._last_tare_at = self.reactor.monotonic()
        self._arm_expires = 0.
        gcmd.respond_info(
            'XL Z unloaded idle accepted %.5f V (offset %+.1f mV from config, '
            'noise %.1f mV p05-p95). RAM only; every G28/PROBE will still '
            'tare, with auto limit %.1f mV.'
            % (avg_v, offset_mv, self._last_tare_noise,
               self.max_idle_deviation_mv))

    def cmd_idle_status(self, gcmd):
        age = None if self._last_tare_at is None else max(
            0., self.reactor.monotonic() - self._last_tare_at)
        gcmd.respond_info(
            'XL Z idle: configured %.5f V; approved %.5f V; '
            'last tare %s; auto guard +/-%.1f mV; manual envelope +/-%.1f mV'
            % (self.reference_idle_v, self._approved_idle_v,
               'none' if age is None else '%.0f s ago' % age,
               self.max_idle_deviation_mv, self.manual_idle_limit_mv))


    def _read_park_reference(self):
        path = self._park_reference_file
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('schema') != 1:
                raise ValueError('unsupported schema')
            value = float(data['voltage_v'])
            if not math.isfinite(value) or not self.raw_min_v < value < self.raw_max_v:
                raise ValueError('reference out of range')
            return value
        except (OSError, ValueError, KeyError, TypeError) as err:
            raise self.printer.config_error(
                'XL CHECK MECHANIC FAILURE: corrupted park reference %s: %s'
                % (path, err))

    def _write_park_reference(self, voltage_v):
        path = self._park_reference_file
        tmp = path.with_name(path.name + '.tmp')
        data = {'schema': 1, 'voltage_v': float(voltage_v)}
        try:
            with tmp.open('x', encoding='utf-8') as stream:
                json.dump(data, stream, sort_keys=True)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(tmp), str(path))
        except OSError as err:
            if tmp.exists():
                tmp.unlink()
            raise self.printer.command_error(
                'XL PARK TARE: cannot persist previous unloaded zero: %s' % err)
        self._park_reference_v = voltage_v

    def cmd_park_reference(self, gcmd):
        old = self._park_reference_v
        gcmd.respond_info(
            'XL PARK REFERENCE: %s; max difference %.0f mV; saved in %s'
            % ('NONE (first accepted tare will initialize)' if old is None
               else '%.5f V' % old, self.park_previous_limit_mv,
               self._park_reference_file))

    def cmd_park_reference_reset(self, gcmd):
        if gcmd.get_int('CONFIRM', 0) != 1:
            raise gcmd.error('XL CHECK MECHANIC FAILURE: inspect unloaded head; then CONFIRM=1')
        toolhead = self.printer.lookup_object('toolhead')
        axes = toolhead.get_status(self.reactor.monotonic()).get('homed_axes', '')
        if not all(a in axes for a in ('x','y')) or toolhead.get_position()[0] > self.park_x_max:
            raise gcmd.error('XL CHECK MECHANIC FAILURE: home XY, park outside glass first')
        if self._home_prepared or self._probe_active or self._limited_home_active:
            raise gcmd.error('XL PARK REFERENCE: cannot reset during probe or homing')
        path = self._park_reference_file
        if path.exists():
            path.unlink()
        self._park_reference_v = None
        self._park_tare = None
        gcmd.respond_info('XL PARK REFERENCE CLEARED; next unloaded parked tare establishes first reference')

    def cmd_home_limited(self, gcmd):
        # Explicitly limited proximity test/short home. Never call normal
        # G28.1 Z: its default 927mm search exceeds available mechanics.
        if gcmd.get_int('CONFIRM', 0) != 1:
            raise gcmd.error('XL Z LIMITED: confirmation required')
        travel = gcmd.get_float('TRAVEL', self.max_limited_home_mm,
                                 above=0., maxval=self.max_limited_home_mm)
        if self._park_tare is None:
            raise gcmd.error('XL Z LIMITED: require XL_Z_PARK_TARE outside glass')
        if self.reactor.monotonic() - self._park_tare[2] > self.park_max_age_s:
            raise gcmd.error('XL Z LIMITED: parked zero expired')
        toolhead = self.printer.lookup_object('toolhead')
        status = toolhead.get_status(self.reactor.monotonic())
        if not all(a in status.get('homed_axes','') for a in ('x','y')):
            raise gcmd.error('XL Z LIMITED: home XY first')
        pos = list(toolhead.get_position())
        if not (20. <= pos[0] <= 300. and 20. <= pos[1] <= 280.):
            raise gcmd.error('XL Z LIMITED: X/Y must be within test glass zone')
        if self._z_homing_positive_dir is not False or self._z_retract > 0.:
            raise gcmd.error('XL Z LIMITED: invalid Z endstop direction/retract')
        self._check_all_z_motors()
        # Deliberate coarse-position operator gate: physical nozzle must
        # already be near the bed with clearance < TRAVEL. The software
        # cannot infer a physical gap without a valid Z reference.
        from . import homing
        self._limited_home_active = True
        try:
            pos[2] = travel
            toolhead.set_position(pos, homing_axes='z')
            target = list(pos)
            target[2] = 0.
            hmove = homing.HomingMove(self.printer, [(self, 'malevich_xl_z_limited')])
            hmove.homing_move(target, self.limited_home_speed,
                              probe_pos=True, triggered=True,
                              check_triggered=True)
            # Contact found at nominal nozzle Z=0; clear the ~1 kgf
            # load by lowering the bed immediately after stopping.
            triggerpos = list(toolhead.get_position())
            triggerpos[2] = 0.
            toolhead.set_position(triggerpos, homing_axes='z')
            clearance = list(triggerpos)
            clearance[2] = self.limited_home_retract_mm
            toolhead.manual_move(clearance, 1.0)
            toolhead.wait_moves()
            gcmd.respond_info('XL Z LIMITED HOME: MCU HIT, Z=0 at contact; released to Z=%.2f. '
                              'Verify nozzle/glass geometry before printing.'
                              % self.limited_home_retract_mm)
        except Exception:
            # Never retain a false Z home after a missed trigger or error.
            toolhead.get_kinematics().clear_homing_state('z')
            raise
        finally:
            self._limited_home_active = False

    def cmd_home_two_stage(self, gcmd):
        """Z home without an initial known Z, stopped by MCU on both passes.

        The coarse threshold is deliberately lower than the final force
        threshold: measured nozzle deformation was only ~0.59mm from
        baseline+200mV to ADC saturation. A rapid 1493mV coarse homing
        would consume that entire window before the MCU filter responds.
        """
        if gcmd.get_int('CONFIRM', 0) != 1:
            raise gcmd.error('XL TWO STAGE: CONFIRM=1 required')
        travel = gcmd.get_float('TRAVEL', self._z_max, above=0.,
                                 maxval=self._z_max)
        coarse_speed = gcmd.get_float('COARSE_SPEED', 3.0, above=0., maxval=5.0)
        coarse_mv = gcmd.get_float('COARSE_MV', 200.0, minval=100., maxval=500.)
        fine_speed = gcmd.get_float('FINE_SPEED', 0.15, above=0., maxval=0.5)
        retract = gcmd.get_float('RETRACT', 2.0, above=0., maxval=5.)
        fine_travel = gcmd.get_float('FINE_TRAVEL', 4.0,
                                     above=retract, maxval=10.)
        if self._limited_home_active or self._probe_active or self._two_stage_active:
            raise gcmd.error('XL TWO STAGE: another probe/homing is active')
        if not self.require_park_tare:
            raise gcmd.error('XL TWO STAGE: off-bed tare required')
        parked = self._park_tare
        if parked is None:
            raise gcmd.error('XL TWO STAGE: XL_Z_PARK_TARE required first')
        if self.reactor.monotonic() - parked[2] > self.park_max_age_s:
            raise gcmd.error('XL TWO STAGE: parked tare expired')
        if self._z_homing_positive_dir is not False or self._z_retract > 0.:
            raise gcmd.error('XL TWO STAGE: Z direction/retract invalid')
        toolhead = self.printer.lookup_object('toolhead')
        status = toolhead.get_status(self.reactor.monotonic())
        if not all(a in status.get('homed_axes', '') for a in ('x', 'y')):
            raise gcmd.error('XL TWO STAGE: home XY first')
        pos = list(toolhead.get_position())
        if not (20. <= pos[0] <= 300. and 20. <= pos[1] <= 280.):
            raise gcmd.error('XL TWO STAGE: place nozzle inside glass test zone')
        self._check_all_z_motors()
        # Reject an already loaded or floating sensor. Do not use a false
        # early trigger to declare Z homed. This is a check, NOT a tare.
        toolhead.wait_moves()
        idle_mv = (self._value() - parked[0] * self.vref) * 1000.
        if idle_mv >= coarse_mv - 30.:
            raise gcmd.error('XL TWO STAGE: PB1 already %+0.0fmV above parked zero '
                             '(coarse threshold %.0fmV); cannot fast-home'
                             % (idle_mv, coarse_mv))
        from . import homing
        self._two_stage_active = True
        try:
            # Stage 1: synthetic Z reference authorizes one long, *MCU*
            # terminated downward move without requiring prior G28 Z.
            self._two_stage_trigger_mv = coarse_mv
            self._park_tare = parked
            pos[2] = travel
            toolhead.set_position(pos, homing_axes='z')
            target = list(pos)
            target[2] = 0.
            gcmd.respond_info('XL Z COARSE: travel <= %.1fmm, speed %.2fmm/s, '
                              'trigger +%.0fmV (MCU)' % (travel, coarse_speed, coarse_mv))
            coarse = homing.HomingMove(self.printer,
                                      [(self, 'malevich_xl_z_coarse')])
            coarse.homing_move(target, coarse_speed, probe_pos=True,
                               triggered=True, check_triggered=True)
            coarse_halt = list(toolhead.get_position())
            gcmd.respond_info('XL Z COARSE HIT: moved %.3fmm; retracting %.2fmm'
                              % (travel - coarse_halt[2], retract))

            # Stage 2: discard the synthetic coarse coordinate, but not the
            # actual stepper positions. Retract physically, then adopt a
            # temporary frame where final Z probe has fine_travel available.
            coarse_halt[2] = 0.
            toolhead.set_position(coarse_halt, homing_axes='z')
            up = list(coarse_halt)
            up[2] = retract
            toolhead.manual_move(up, min(1.0, self.max_probe_speed))
            toolhead.wait_moves()
            up[2] = fine_travel
            toolhead.set_position(up, homing_axes='z')
            self._two_stage_trigger_mv = self.threshold_mv
            self._park_tare = parked
            target = list(up)
            target[2] = 0.
            gcmd.respond_info('XL Z FINE: speed %.3fmm/s, trigger +%.0fmV '
                              '(MCU), travel <= %.1fmm'
                              % (fine_speed, self.threshold_mv, fine_travel))
            fine = homing.HomingMove(self.printer,
                                    [(self, 'malevich_xl_z_fine')])
            fine.homing_move(target, fine_speed, probe_pos=True,
                             triggered=True, check_triggered=True)
            at_contact = list(toolhead.get_position())
            at_contact[2] = 0.
            toolhead.set_position(at_contact, homing_axes='z')
            clear = list(at_contact)
            clear[2] = self.limited_home_retract_mm
            toolhead.manual_move(clear, 1.0)
            toolhead.wait_moves()
            gcmd.respond_info('XL Z TWO STAGE HOME: COARSE HIT + FINE HIT; '
                              'Z=0 at fine contact, released to Z=%.2f'
                              % self.limited_home_retract_mm)
        except Exception:
            toolhead.get_kinematics().clear_homing_state('z')
            raise
        finally:
            self._two_stage_active = False
            self._two_stage_trigger_mv = None
            self._park_tare = None  # no orphaned armed tare after home

    def cmd_prehome_clear(self, gcmd):
        """Lower bed (+Z) before G28 XY motion, even when Z is not homed.

        A temporary Z reference exists ONLY for the physical clearance move;
        the Z homed state is unconditionally cleared before G28 proceeds.
        No movement is issued towards the nozzle in this method.
        """
        distance = gcmd.get_float('DISTANCE', 3.0, above=0., maxval=10.)
        speed = gcmd.get_float('SPEED', 2.0, above=0., maxval=5.)
        if self._two_stage_active or self._limited_home_active or self._probe_active:
            raise gcmd.error('XL PREHOME: Z probe/home already active')
        th = self.printer.lookup_object('toolhead')
        th.wait_moves()
        pos = list(th.get_position())
        homed = th.get_status(self.reactor.monotonic()).get('homed_axes', '')
        if 'z' in homed:
            if pos[2] + distance > self._z_max + 0.00001:
                raise gcmd.error('XL PREHOME: Z already too close to position_max')
            start_z = pos[2]
        else:
            # Unhomed Z: temporarily map the present physical position to
            # Z=0, allowing ONLY a positive (+Z, bed lowering) clearance.
            # This does not home the axis: clear_homing_state() below is
            # unconditional, including if movement fails.
            pos[2] = 0.0
            th.set_position(pos, homing_axes='z')
            start_z = 0.0
        try:
            target = list(th.get_position())
            target[2] = start_z + distance
            th.manual_move(target, speed)
            th.wait_moves()
            gcmd.respond_info('XL PREHOME: bed lowered %.2f mm before XY homing/tare'
                              % distance)
        finally:
            th.get_kinematics().clear_homing_state('z')
            # Keep gcode move state synchronized with the temporary toolhead
            # frame; G28 will establish the real Z origin later.
            self.printer.lookup_object('gcode_move').reset_last_position()

    def _take_park_baseline(self):
        # An unsuccessful new tare must never leave a previously armed tare
        # usable by G28 or PROBE.
        self._park_tare = None
        toolhead = self.printer.lookup_object('toolhead')
        status = toolhead.get_status(self.reactor.monotonic())
        axes = status.get('homed_axes', '')
        if not all(axis in axes for axis in ('x', 'y')):
            raise self.printer.command_error('XL PARK TARE: home X and Y first')
        pos = toolhead.get_position()
        if pos[0] > self.park_x_max + 1e-3:
            raise self.printer.command_error(
                'XL PARK TARE: X=%.2f is not outside glass (must be <= %.2f)'
                % (pos[0], self.park_x_max))
        if self._home_prepared or self._probe_active:
            raise self.printer.command_error('XL PARK TARE: trigger already active')
        toolhead.wait_moves()
        # Wait at the parked XY position so the sampling window is not taken
        # during a move. MCU timestamps still checked by _read_stable_idle().
        self.reactor.pause(self.reactor.monotonic() +
                           max(self.park_settle_s, self.tare_window_s + 0.15))
        avg, noise, last_t = self._read_stable_idle(self.park_max_noise_mv)
        noise_mv = noise * self.vref * 1000.
        if noise_mv >= self.threshold_mv:
            raise self.printer.command_error(
                'XL PARK TARE: noise %.1f mV >= threshold %.1f mV'
                % (noise_mv, self.threshold_mv))
        # Compare with the LAST successful off-bed reading, not the
        # original OEM voltage. Reject a >500mV jump and do NOT update file.
        voltage_v = avg * self.vref
        previous_v = self._park_reference_v
        if previous_v is not None:
            change_mv = (voltage_v - previous_v) * 1000.
            if abs(change_mv) > self.park_previous_limit_mv:
                raise self.printer.command_error(
                    'XL CHECK MECHANIC FAILURE: unloaded parked PB1 changed '
                    '%+.1f mV (previous %.5f V, now %.5f V, limit %.0f mV). '
                    'Inspect PTFE, cable chain, hotend and strain gauge.'
                    % (change_mv, previous_v, voltage_v, self.park_previous_limit_mv))
        # A relative trigger cannot work if the positive ADC rail is reached
        # before the requested delta. Reject it before caching a tare.
        # Reserve 50mV for ADC headroom; this is not a mechanical force limit.
        max_trigger_v = self.raw_max_v - 0.050
        trigger_v = avg * self.vref + self.threshold_mv / 1000.
        if trigger_v >= max_trigger_v:
            raise self.printer.command_error(
                'XL PARK TARE: baseline %.4f V + threshold %.0f mV '
                'exceeds ADC usable range %.4f V'
                % (avg * self.vref, self.threshold_mv, max_trigger_v))
        # Persist before arming: any storage error fails closed.
        self._write_park_reference(voltage_v)
        # Make QUERY_PROBE and diagnostics use the same parked zero.
        self.baseline_frac = avg
        self._last_tare_noise = noise_mv
        self._last_tare_at = self.reactor.monotonic()
        self._park_tare = (avg, noise_mv, self._last_tare_at)
        return avg * self.vref, noise_mv

    def cmd_park_tare(self, gcmd):
        if self._arm_expires > self.reactor.monotonic():
            raise gcmd.error('XL PARK TARE: do not tare while G28 is armed')
        v, noise_mv = self._take_park_baseline()
        gcmd.respond_info(
            'XL PARK TARE: %.5f V, p05-p95 %.1f mV; next trigger uses this zero once (max age %.0fs)'
            % (v, noise_mv, self.park_max_age_s))

    def cmd_park_status(self, gcmd):
        info = self._park_tare
        if info is None:
            gcmd.respond_info('XL PARK TARE: none pending')
        else:
            gcmd.respond_info('XL PARK TARE: %.5f V, noise %.1f mV, age %.1fs, threshold %.1f mV'
                              % (info[0]*self.vref, info[1],
                                 self.reactor.monotonic()-info[2], self.threshold_mv))

    def cmd_park_compare(self, gcmd):
        parked = self._park_tare
        if parked is None:
            raise gcmd.error('XL PARK COMPARE: take XL_Z_PARK_TARE first')
        raw_now = self._value()
        delta = (raw_now - parked[0]*self.vref)*1000.
        margin = self.threshold_mv - delta
        gcmd.respond_info(
            'XL PARK COMPARE: parked %.5f V, here %.5f V, delta %+.1f mV; '
            'contact threshold +%.1f mV; positive margin %.1f mV'
            % (parked[0]*self.vref, raw_now, delta, self.threshold_mv, margin))

    def _setup_trigger(self):
        if self.require_park_tare:
            parked = self._park_tare
            self._park_tare = None  # one-shot even if setup fails
            if parked is None:
                raise self.printer.command_error(
                    'XL Z: off-bed baseline missing; move to X<0 and run XL_Z_PARK_TARE')
            # A session keeps its original off-bed zero for the whole multi-point
            # measurement; the 300s limit still applies to manual/limited G28.
            if (self.reactor.monotonic() - parked[2] > self.park_max_age_s
                and not (self._probe_active and self._probe_session_park is not None)):
                raise self.printer.command_error('XL Z: off-bed baseline expired')
            # Do not update zero after returning over the glass.
            self.baseline_frac = parked[0]
            self._last_tare_noise = parked[1]
            self._last_tare_at = parked[2]
            avg_v = parked[0] * self.vref
        else:
            avg_v = self._tare()
        # Recheck at arming time as runtime SET_THRESHOLD can change the delta.
        # ADC saturation is not a reliable contact detector.
        # Coarse pass only: low-force stop. Standard probe and G28 fine
        # preserve the calibrated 1493mV force trigger.
        threshold_mv = (
            self._probe_coarse_effective_mv
            if self._probe_active and self._probe_coarse_phase
            else self._two_stage_trigger_mv
            if self._two_stage_active else self.threshold_mv)
        if threshold_mv is None:
            raise self.printer.command_error('XL TWO STAGE: trigger phase not selected')
        if avg_v + threshold_mv / 1000. >= self.raw_max_v - 0.050:
            raise self.printer.command_error(
                'XL Z: no ADC headroom for %.0f mV trigger from %.4f V baseline'
                % (threshold_mv, avg_v))
        threshold_frac = threshold_mv / 1000. / self.vref
        baseline_counts = int(round(self.baseline_frac * ADC_MAX))
        delta_counts = max(1, int(round(threshold_frac * ADC_MAX)))
        self._trigger.set_raw_range(
            int(round(self.raw_min_v / self.vref * ADC_MAX)),
            int(round(self.raw_max_v / self.vref * ADC_MAX)))
        sos = self._trigger.get_sos_filter()
        # sos may be initialized in MCU_trigger_analog's config callback.
        if sos is None:
            raise self.printer.command_error('XL Z: MCU analog filter unavailable')
        sos.set_offset_scale(-baseline_counts, 1.)
        self._trigger.set_trigger('gt', delta_counts)
        return avg_v

    # Standard endstop API; mcu.py's homing transport uses this object.
    def setup_pin(self, pin_type, pin_params):
        if (pin_type != 'endstop' or pin_params['pin'] != 'virtual_endstop'
            or pin_params['invert'] or pin_params['pullup']):
            raise self.printer.config_error(
                'XL Z requires endstop_pin: malevich_xl_z_probe:virtual_endstop')
        return self

    def get_mcu(self):
        return self._mcu

    def add_stepper(self, stepper):
        self._trigger.get_dispatch().add_stepper(stepper)

    def get_steppers(self):
        return self._trigger.get_steppers()

    def _check_test_bounds(self, actual_start_z=None):
        # This check is NOT a physical-distance sensor. The operator must also
        # confirm a larger real nozzle-to-bed clearance and unobstructed travel.
        if not self.allow_homing:
            raise self.printer.command_error(
                'XL Z homing BLOCKED: allow_homing is false')
        if self._z_homing_positive_dir is not False:
            raise self.printer.command_error(
                'XL Z homing BLOCKED: explicitly set homing_positive_dir: false')
        if self._z_homing_speed > self.max_test_speed:
            raise self.printer.command_error(
                'XL Z homing BLOCKED: homing_speed %.3f > %.3f mm/s'
                % (self._z_homing_speed, self.max_test_speed))
        if self._z_retract > 0:
            raise self.printer.command_error(
                'XL Z homing BLOCKED: homing_retract_dist must be 0')
        if self._z_max <= self._z_endstop or self._z_endstop < self._z_min:
            raise self.printer.command_error(
                'XL Z homing BLOCKED: invalid Z homing direction/range')
        # CoreXY Kinematics.home() uses 1.5x range for negative homing.
        nominal_travel = 1.5 * (self._z_max - self._z_endstop)
        if nominal_travel > self.max_test_travel_mm + 1e-6:
            raise self.printer.command_error(
                'XL Z homing BLOCKED: proposed G28 Z travel %.2f mm > %.2f mm'
                % (nominal_travel, self.max_test_travel_mm))
        if actual_start_z is not None:
            real_commanded = actual_start_z - self._z_endstop
            if (not math.isfinite(real_commanded)
                    or real_commanded < -1e-6
                    or real_commanded > self.max_test_travel_mm + 1e-6):
                raise self.printer.command_error(
                    'XL Z homing BLOCKED: actual planned Z travel %.2f mm'
                    % real_commanded)
        return nominal_travel

    def _check_all_z_motors(self):
        names = {s.get_name() for s in self._trigger.get_steppers()}
        expected = {'stepper_z', 'stepper_z1', 'stepper_z2', 'stepper_z3'}
        if names != expected:
            raise self.printer.command_error(
                'XL Z homing BLOCKED: expected 4 steppers, got %s'
                % ', '.join(sorted(names)))

    def _on_homing_move_begin(self, hmove):
        # Runs BEFORE HomingMove computes its print_time and arms trsync.
        # Any host-side 0.24s tare delay must happen here, not in home_start().
        if self not in hmove.get_mcu_endstops():
            return
        self._home_prepared = False
        expires = self._arm_expires
        if not (self._probe_active or self._limited_home_active or self._two_stage_active):
            self._arm_expires = 0.  # consume for legacy G28 only
        if (not self._probe_active and not self._limited_home_active
            and not self._two_stage_active and self.arm_required
            and (expires <= 0. or self.reactor.monotonic() > expires)):
            raise self.printer.command_error(
                'XL Z homing BLOCKED: run XL_Z_ARM CONFIRM=1 before G28 Z')
        if self._two_stage_active:
            # Two-stage homing owns the temporary Z frame. Do not
            # apply the old <=5/30mm limited-home proximity restriction.
            actual_start_z = hmove.toolhead.get_position()[2]
            if (not math.isfinite(actual_start_z) or actual_start_z <= 0.
                or actual_start_z > self._z_max + 0.000001):
                raise self.printer.command_error('XL TWO STAGE: invalid search distance')
        elif self._limited_home_active:
            actual_start_z = hmove.toolhead.get_position()[2]
            # The endpoint of the local HomingMove is set by cmd_home_limited.
            if actual_start_z <= 0. or actual_start_z > self.max_limited_home_mm + 1.e-6:
                raise self.printer.command_error('XL Z LIMITED: invalid start distance')
            if self.limited_home_speed > 1.0:
                raise self.printer.command_error('XL Z LIMITED: speed too high')
        elif self._probe_active:
            # PROBE must only travel a short, bounded distance from a
            # previously homed position. Its target is position_min, not
            # the full virtual G28 homing distance.
            if not self.allow_probing:
                raise self.printer.command_error('XL standard PROBE is disabled')
            if self._z_homing_positive_dir is not False:
                raise self.printer.command_error(
                    'XL PROBE: homing_positive_dir must be false')
            speed_limit = (self.probe_coarse_speed if self._probe_coarse_phase
                           else self.max_probe_speed)
            if (self._probe_speed is None or self._probe_speed > speed_limit):
                raise self.printer.command_error(
                    'XL PROBE: requested speed exceeds stage speed limit')
            start_z = hmove.toolhead.get_position()[2]
            travel = start_z - self._z_min
            if (not math.isfinite(travel) or travel <= 0.
                or travel > self.max_probe_travel_mm):
                raise self.printer.command_error(
                    'XL PROBE: %.3f mm travel outside (0, %.3f] mm'
                    % (travel, self.max_probe_travel_mm))
        else:
            self._check_test_bounds(hmove.toolhead.get_position()[2])
        self._check_all_z_motors()
        # Flush previously queued motion BEFORE acquiring the unloaded zero.
        hmove.toolhead.wait_moves()
        self._setup_trigger()  # no MCU homing is active yet
        # Pre-arm time reserve; added BEFORE HomingMove captures print_time.
        # Avoid queuing trigger_analog_home too close to MCU now when
        # UART retries / ADC reports delay delivery of setup commands.
        hmove.toolhead.dwell(0.5)
        self._home_prepared = True

    def home_start(self, print_time, sample_time, sample_count, rest_time,
                   triggered=True):
        # No host ADC reads, sleeps, or taring after print_time is captured.
        prepared = self._home_prepared
        self._home_prepared = False
        if not prepared or not (self.allow_homing or self._limited_home_active or
                                self._two_stage_active or
                                (self._probe_active and self.allow_probing)):
            raise self.printer.command_error(
                'XL Z homing BLOCKED: preflight or arm missing')
        if not triggered:
            raise self.printer.command_error('XL Z homing expects positive trigger')
        return self._trigger.home_start(print_time, sample_time, sample_count,
                                        rest_time, triggered=triggered)

    def home_wait(self, home_end_time):
        try:
            return self._trigger.home_wait(home_end_time)
        finally:
            self._arm_expires = 0.
            self._home_prepared = False

    def query_endstop(self, print_time):
        voltage = self._value()
        if self.baseline_frac is None:
            raise self.printer.command_error('XL PB1: run MALEVICH_XL_TARE')
        return voltage - self.baseline_frac * self.vref > self.threshold_mv / 1000.

    def cmd_tare(self, gcmd):
        baseline = self._tare()
        gcmd.respond_info('XL PB1 tare: baseline %.5f V, noise %.2f mV'
                          % (baseline, self._last_tare_noise))

    def cmd_status(self, gcmd):
        voltage = self._value()
        base = self.baseline_frac * self.vref if self.baseline_frac is not None else None
        if base is None:
            gcmd.respond_info('XL PB1: %.5f V; not tared (MALEVICH_XL_TARE)'
                              % voltage)
        else:
            delta_mv = (voltage - base) * 1000
            triggered = int(delta_mv > self.threshold_mv)
            gcmd.respond_info(
                'XL PB1: %.5f V, baseline %.5f V, delta %+.1f mV, '
                'threshold %.1f mV, triggered=%d (diagnostic)'
                % (voltage, base, delta_mv, self.threshold_mv, triggered))
        if self._supply_adc is not None:
            _, frac = self._supply_adc.get_last_value()
            gcmd.respond_info('XL PA0: ADC %.6f, supply %.3f V'
                              % (frac, frac * self._supply_fullscale))

    def cmd_adc_debug(self, gcmd):
        # Diagnostic only; never used to stop motion.
        if not self.samples:
            gcmd.respond_info('XL ADC: no samples')
            return
        recent = list(self.samples)
        last_time = recent[-1][0]
        n240 = sum(1 for t, v in recent if last_time - t <= 0.24)
        n1000 = sum(1 for t, v in recent if last_time - t <= 1.0)
        last = recent[-min(64, len(recent)):]
        span = max(0., last[-1][0] - last[0][0])
        rate = (len(last) - 1) / span if span > 0. else 0.
        age = self._mcu.estimated_print_time(self.reactor.monotonic()) - last_time
        gcmd.respond_info(
            'XL ADC: buffered=%d, last_240ms=%d, last_1s=%d, '
            'estimated_rate=%.1f Hz, last_age=%.3f s, PB1=%.5f V'
            % (len(recent), n240, n1000, rate, age,
               recent[-1][1] * self.vref))

    def cmd_adc_stats(self, gcmd):
        # Diagnostics only; do not smooth, replace, or override safety limits.
        # Percentiles distinguish isolated spikes from broad continuous noise.
        if not self.samples:
            gcmd.respond_info('XL ADC STATS: no samples')
            return
        recent = list(self.samples)
        last_time = recent[-1][0]
        for window in (0.24, 1.0):
            values = sorted(v * self.vref * 1000. for t, v in recent
                            if last_time - window <= t <= last_time)
            n = len(values)
            if n < 5:
                gcmd.respond_info('XL ADC STATS %.2fs: only %d samples'
                                  % (window, n))
                continue
            def percentile(q):
                idx = (n - 1) * q
                lo = int(idx)
                hi = min(lo + 1, n - 1)
                return values[lo] + (values[hi] - values[lo]) * (idx - lo)
            avg = statistics.mean(values)
            sd = statistics.pstdev(values)
            p05, p50, p95 = (percentile(0.05), percentile(0.5),
                             percentile(0.95))
            gcmd.respond_info(
                'XL ADC STATS %.2fs: n=%d mean=%.2f mV, median=%.2f mV, '
                'min=%.2f, max=%.2f, pp=%.2f mV, p05=%.2f, p95=%.2f, '
                'p05-p95=%.2f mV, sd=%.2f mV'
                % (window, n, avg, p50, values[0], values[-1],
                   values[-1] - values[0], p05, p95, p95 - p05, sd))

    def cmd_threshold(self, gcmd):
        proposed_mv = gcmd.get_float('MV', minval=10., maxval=2000.)
        if self._home_prepared or self._probe_active or self._arm_expires > self.reactor.monotonic():
            raise gcmd.error('XL Z: cannot change threshold while armed/probing')
        if self._park_tare is not None:
            baseline_v = self._park_tare[0] * self.vref
            if baseline_v + proposed_mv / 1000. >= self.raw_max_v - 0.050:
                raise gcmd.error('XL Z threshold exceeds ADC headroom for parked zero')
        self.threshold_mv = proposed_mv
        gcmd.respond_info('XL Z threshold: %.1f mV' % self.threshold_mv)

    def cmd_filter_info(self, gcmd):
        gcmd.respond_info(
            'XL Z MCU FILTER: %d SOS first-order lowpass sections, '
            'cutoff %.1f Hz, ADC %d Hz; applied before MCU trigger_analog; '
            'homing_allowed=%s'
            % (self._mcu_filter_stages, self.mcu_filter_hz, self.rate_hz,
               self.allow_homing))

    def cmd_test_bounds(self, gcmd):
        # A read-only preview is available even while motion is disabled.
        distance = 1.5 * (self._z_max - self._z_endstop)
        gcmd.respond_info(
            'XL Z PREVIEW: planned search %.2f mm at %.2f mm/s; '
            'limit %.2f mm / %.2f mm/s; allow_homing=%s; NO MOVEMENT'
            % (distance, self._z_homing_speed, self.max_test_travel_mm,
               self.max_test_speed, self.allow_homing))
        try:
            self._check_test_bounds()
            self._check_all_z_motors()
        except self.printer.command_error as exc:
            gcmd.respond_info('XL Z BOUNDS: BLOCKED (%s)' % exc)
            return
        gcmd.respond_info(
            'XL Z BOUNDS: SOFTWARE PRECHECK OK. Physical clearance and '
            'motion direction are NOT verified.')

    def cmd_trigger_test(self, gcmd):
        # Stationary end-to-end MCU analog / trsync verification.  This uses
        # real MCU trigger_analog HOME/WAIT calls, but issues NO G-code move.
        # Must stay disabled while experimental G28 Z could be enabled.
        if self.allow_homing:
            raise gcmd.error('XL_Z_TRIGGER_TEST requires allow_homing: False')
        timeout = gcmd.get_float('SECONDS', 4., minval=1., maxval=10.)
        toolhead = self.printer.lookup_object('toolhead')
        # Wait for ALL already queued moves before dispatching stepper_stop.
        # Do not test while printing or while other clients issue moves.
        toolhead.wait_moves()
        self._setup_trigger()  # tare unloaded; set raw range, threshold and MCU offset
        print_time = toolhead.get_last_move_time()
        # This starts the SAME trigger_analog+trsync path that G28 Z will use,
        # but does NOT schedule motion.  Result is nonzero only for MCU trigger.
        self._trigger.home_start(print_time, 0., 0, 0.)
        trigger_time = self._trigger.home_wait(print_time + timeout)
        if trigger_time:
            gcmd.respond_info(
                'XL Z MCU TRSYNC: HIT (manual pressure detected; no movement)')
        else:
            gcmd.respond_info('XL Z MCU TRSYNC: TIMEOUT (no trigger; no movement)')

    def cmd_arm(self, gcmd):
        if not self.arm_required:
            gcmd.respond_info('XL Z: arm_required=False; G28 Z can run directly after preflight')
            return
        if not self.allow_homing:
            raise gcmd.error('XL Z cannot arm: allow_homing=false in config')
        if gcmd.get_int('CONFIRM', 0) != 1:
            raise gcmd.error('XL Z requires XL_Z_ARM CONFIRM=1')
        # Reject unsafe G28 parameters before arming anything.
        self._check_test_bounds()
        self._check_all_z_motors()
        # If parked tare is required, retain it for _setup_trigger after XY
        # moves to glass; do not tare a second time over the glass.
        if self.require_park_tare:
            parked = self._park_tare
            if parked is None or self.reactor.monotonic()-parked[2] > self.park_max_age_s:
                raise gcmd.error('XL Z: run XL_Z_PARK_TARE at X<0 before arming')
        else:
            self._tare()
        self._arm_expires = self.reactor.monotonic() + self.arm_seconds
        gcmd.respond_info('XL Z armed for ONE homing start (%.0fs). '
                          'Verify a physical clear travel limit first.'
                          % self.arm_seconds)

    # --- Optional Klipper standard Probe API; MCU trigger path is unchanged ---
    def get_probe_params(self, gcmd=None):
        return self._probe_params.get_probe_params(gcmd)

    def get_offsets(self, gcmd=None):
        return self._probe_offsets.get_offsets(gcmd)

    def start_probe_session(self, gcmd):
        if not self.allow_probing:
            raise self.printer.command_error(
                'XL standard PROBE disabled: set allow_probing: True '
                'only after stationary MCU trigger tests')
        return self._probe_session.start_probe_session(gcmd)

    def _begin_probe_session(self, gcmd):
        self._probe_homing.clear_trigger_positions()
        self._probe_session_park = None
        if self.require_park_tare and self.auto_park_probe:
            # Called once at session start, BEFORE Klipper sends XY
            # to point 1. Stay at park; caller will move to point 1.
            self.gcode.respond_info(
                'XL PROBE SESSION: initial tare before first XY point')
            cmd_name = gcmd.get_command()
            points_command = cmd_name in ('BED_MESH_CALIBRATE',
                                          'Z_TILT_ADJUST')
            self.gcode.respond_info('XL PROBE SESSION: %s, restore XY=%s'
                                    % (cmd_name, not points_command))
            self._auto_park_probe_tare(return_to_origin=not points_command)
            self._probe_session_park = self._park_tare
        return self

    def _auto_park_probe_tare(self, return_to_origin=True):
        if not self.require_park_tare or not self.auto_park_probe:
            return
        toolhead = self.printer.lookup_object('toolhead')
        axes = toolhead.get_status(self.reactor.monotonic()).get('homed_axes', '')
        if not all(axis in axes for axis in ('x', 'y', 'z')):
            raise self.printer.command_error('XL PROBE: auto park requires homed XYZ')
        p = list(toolhead.get_position())
        # Only homed Z may rise to the clearance position. Never assume
        # an unhomed Z coordinate, and never issue an automatic G28 here.
        if p[2] < self.park_safe_z:
            lift = list(p)
            lift[2] = self.park_safe_z
            toolhead.manual_move(lift, min(self.max_probe_speed, 1.0))
        park_pos = list(toolhead.get_position())
        park_pos[0] = self.park_x
        toolhead.manual_move(park_pos, 40.)
        toolhead.wait_moves()
        self._take_park_baseline()
        if return_to_origin:
            back = list(toolhead.get_position())
            back[0], back[1] = p[0], p[1]
            toolhead.manual_move(back, 40.)
            toolhead.wait_moves()

    def _assert_standard_probe_xy(self, stage):
        # The verified XL glass test area. In particular X=-10 is NOT glass.
        p = self.printer.lookup_object('toolhead').get_position()
        if not (19.95 <= p[0] <= 300.05 and 19.95 <= p[1] <= 280.05):
            raise self.printer.command_error(
                'XL PROBE BLOCKED: %s at X%.3f Y%.3f outside glass; no Z motion'
                % (stage, p[0], p[1]))

    def _descend_bounded(self, gcmd, distance, stage):
        # Klipper's DescendToEndstopHelper normally aims at the global Z-min.
        # Temporarily reduce target to a local bounded descent. The low-level
        # MCU trigger_analog -> trsync stop remains entirely native.
        self._assert_standard_probe_xy(stage)
        th = self.printer.lookup_object('toolhead')
        z_start = th.get_position()[2]
        descender = self._probe_homing
        original_zmin = descender.z_min_position
        descender.z_min_position = max(original_zmin, z_start - distance)
        try:
            if descender.z_min_position >= z_start - 0.001:
                raise self.printer.command_error(
                    'XL PROBE: no valid Z descent for %s from %.4f'
                    % (stage, z_start))
            self.gcode.respond_info(
                'XL PROBE %s: X/Y on glass; Z %.3f -> %.3f max (%.2f mm)'
                % (stage, z_start, descender.z_min_position,
                   z_start-descender.z_min_position))
            descender.descend_until_trigger(gcmd)
        finally:
            descender.z_min_position = original_zmin

    def _check_probe_session_idle(self):
        # No Z movement here. Inspect unloaded PB1 at the *current* XY after
        # Klipper has already retracted and moved to the next probe point.
        # Measuring on the glass MUST NOT redefine the zero: only the
        # off-glass parked procedure may do that.
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.wait_moves()
        self.reactor.pause(self.reactor.monotonic() + 0.30)
        try:
            frac, noise, last_time = calculate_baseline(
                self.samples, sample_window_s=0.20,
                min_samples=max(12, self.rate_hz // 8),
                max_noise_fraction=self.park_max_noise_mv / 1000. / self.vref)
        except ValueError as exc:
            raise self.printer.command_error(
                'XL PROBE: pre-contact PB1 reading rejected: %s' % exc)
        now_pt = self._mcu.estimated_print_time(self.reactor.monotonic())
        if not (now_pt - 0.50 <= last_time <= now_pt + 0.05):
            raise self.printer.command_error(
                'XL PROBE: pre-contact PB1 readings are stale')
        parked = self._probe_session_park
        if parked is None:
            raise self.printer.command_error('XL PROBE: session baseline missing')
        delta_mv = (frac - parked[0]) * self.vref * 1000.
        if delta_mv > self.park_recheck_mv:
            # Large positive shift: take a real off-bed tare, after which
            # the new value becomes the session baseline. The existing
            # persisted-reference check (500mV) still applies.
            self.gcode.respond_info(
                'XL PROBE: unloaded PB1 at XY %+0.1f mV above session tare '
                '(limit +%.0f mV); re-parking to re-tare'
                % (delta_mv, self.park_recheck_mv))
            self._auto_park_probe_tare()
            self._probe_session_park = self._park_tare
            if self._probe_session_park is None:
                raise self.printer.command_error(
                    'XL PROBE: re-tare returned no baseline')

    def run_probe(self, gcmd):
        # Session start is before XY movement for BED_MESH/Z_TILT, but a
        # standalone PROBE has no subsequent XY movement. Therefore _begin_
        # probe_session MUST return to caller XY for standalone commands.
        self._assert_standard_probe_xy('run_probe entry')
        if self.require_park_tare and self.auto_park_probe:
            self._check_probe_session_idle()
            # A re-tare can move XY; always verify before Z descent.
            self._assert_standard_probe_xy('after re-tare')
        params = self._probe_params.get_probe_params(gcmd)
        fine_speed = params['probe_speed']
        if fine_speed > self.max_probe_speed:
            raise self.printer.command_error(
                'XL PROBE: fine speed %.3f exceeds %.3f mm/s'
                % (fine_speed, self.max_probe_speed))
        parked = self._probe_session_park
        if self.probe_two_stage and parked is None:
            raise self.printer.command_error('XL PROBE: no session parked zero')
        self._probe_active = True
        try:
            if self.probe_two_stage:
                th = self.printer.lookup_object('toolhead')
                th.wait_moves()
                delta = (self._value() - parked[0]*self.vref) * 1000.
                coarse_mv = max(self.probe_coarse_threshold_mv,
                                delta + self.probe_coarse_threshold_mv)
                if (not math.isfinite(coarse_mv)
                    or coarse_mv >= self.threshold_mv - 400.):
                    raise self.printer.command_error(
                        'XL PROBE: coarse threshold +%.1fmV too close to fine +%.1fmV'
                        % (coarse_mv, self.threshold_mv))
                self._probe_coarse_effective_mv = coarse_mv
                coarse_params = dict(gcmd.get_command_parameters())
                coarse_params['PROBE_SPEED'] = str(self.probe_coarse_speed)
                coarse_gcmd = self.gcode.create_gcode_command(
                    gcmd.get_command(), gcmd.get_commandline(), coarse_params)
                self._probe_coarse_phase = True
                self._probe_speed = self.probe_coarse_speed
                self._park_tare = parked
                self._descend_bounded(coarse_gcmd,
                                      self.probe_coarse_travel_mm, 'COARSE')
                # Discard the coarse point: do not let Klipper average it.
                self._probe_homing.clear_trigger_positions()
                self._probe_coarse_phase = False
                p = list(th.get_position())
                p[2] += self.probe_coarse_retract_mm
                th.manual_move(p, params['lift_speed'])
                th.wait_moves()
                self._park_tare = parked
                self._probe_speed = fine_speed
                self._descend_bounded(gcmd, self.probe_fine_travel_mm, 'FINE')
            else:
                if parked is not None:
                    self._park_tare = parked
                self._probe_speed = fine_speed
                self._descend_bounded(gcmd, self.probe_coarse_travel_mm,
                                      'SINGLE')
        except Exception:
            self._probe_homing.clear_trigger_positions()
            raise
        finally:
            self._probe_coarse_phase = False
            self._probe_coarse_effective_mv = None
            self._probe_active = False
            self._probe_speed = None



    def pull_probed_results(self):
        return self._probe_homing.pull_trigger_positions()

    def end_probe_session(self):
        self._probe_active = False
        self._probe_speed = None
        if self.require_park_tare and self.auto_park_probe:
            self._park_tare = None
        self._probe_session_park = None
        self._probe_homing.clear_trigger_positions()

    def get_status(self, eventtime):
        status = {'armed': self._arm_expires > eventtime,
                'baseline_v': (self.baseline_frac * self.vref
                               if self.baseline_frac is not None else None),
                'threshold_mv': self.threshold_mv,
                'homing_allowed': self.allow_homing,
                'mcu_filter_hz': self.mcu_filter_hz,
                'max_test_travel_mm': self.max_test_travel_mm,
                'arm_required': self.arm_required,
                'probe_bridge_enabled': self.enable_probe_bridge,
                'probing_allowed': self.allow_probing,
                'approved_idle_v': self._approved_idle_v,
                'offbed_tare_required': self.require_park_tare,
                'offbed_tare_pending': self._park_tare is not None,
                'park_previous_v': self._park_reference_v,
                'park_previous_limit_mv': self.park_previous_limit_mv,
                'last_tare_age_s': (None if self._last_tare_at is None else
                                    max(0., eventtime-self._last_tare_at))}
        if self.enable_probe_bridge:
            status.update(self._probe_cmd.get_status(eventtime))
        return status


def load_config(config):
    return MalevichXLZProbe(config)
