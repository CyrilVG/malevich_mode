# Fixed PICASO panel transport; matched firmware required. GPL-3.0-or-later.
import struct
from .uc1701 import DisplayBase, BACKGROUND_PRIORITY_CLOCK

class MalevichPanel(DisplayBase):
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.mcu = self.printer.lookup_object('mcu')
        self.steps = config.getchoice('encoder_steps_per_detent', [2, 4], 2)
        self.reverse = config.getboolean('panel_reverse_encoder', False)
        self.fast_rate = config.getfloat('encoder_fast_rate', .030, above=0.)
        self.contrast = config.getint('contrast', 239, minval=0, maxval=255)
        self.invert = config.getboolean('invert', False)
        self.queue = self.mcu.alloc_command_queue()
        self.mcu.register_config_callback(self.build_config)
        self.running = False
        self.epoch = None
        self.ack = 0
        self.last_direction = None
        self.last_tick = None
        self.stats = {}
        self.poll_timer = self.reactor.register_timer(self.poll)
        self.printer.register_event_handler('klippy:shutdown', self.stop)
        self.printer.register_event_handler('klippy:disconnect', self.stop)
        self.printer.lookup_object('gcode').register_command(
            'HC_PANEL_STATUS', self.cmd_status)
        DisplayBase.__init__(self, self)
        self.sent = [None] * 32

    def send(self, data, is_data=False):
        raise RuntimeError('Panel uses addressed framebuffer transfers')

    def build_config(self):
        if self.mcu.get_constants().get('MALEVICH_PANEL_VERSION') != 1:
            raise self.printer.config_error('Matched malevich panel firmware required')
        self.start_cmd = self.mcu.lookup_command(
            'panel_start steps=%c contrast=%c invert=%c', cq=self.queue)
        self.frame_cmd = self.mcu.lookup_command(
            'panel_frame offset=%hu data=%*s', cq=self.queue)
        self.query_cmd = self.mcu.lookup_query_command(
            'panel_query ack=%u', 'panel_events epoch=%u seq=%u tick=%u data=%*s',
            cq=self.queue)
        self.status_cmd = self.mcu.lookup_query_command(
            'panel_get_status',
            'panel_status raw=%c online=%c visible=%c overflow=%u invalid=%u max_scan_ticks=%u',
            cq=self.queue)

    def init(self):
        self.start_cmd.send([self.steps, self.contrast, int(self.invert)])
        self.running = True
        self.sent = [None] * 32
        self.reactor.update_timer(self.poll_timer, self.reactor.NOW)

    def stop(self, *args):
        self.running = False
        self.reactor.update_timer(self.poll_timer, self.reactor.NEVER)

    def flush(self):
        for page in range(8):
            for col in range(0, 128, 32):
                index = page * 4 + col // 32
                data = bytes(self.vram[page][col:col+32])
                if self.sent[index] != data:
                    self.frame_cmd.send([index * 32, data],
                                        reqclock=BACKGROUND_PRIORITY_CLOCK)
                    self.sent[index] = data

    def poll(self, eventtime):
        if not self.running:
            return self.reactor.NEVER
        try:
            result = self.query_cmd.send([self.ack])
            received = self.reactor.monotonic()
            data = bytes(result['data'])
            if len(data) % 5:
                raise ValueError('Malformed panel events')
            menu = self.printer.lookup_object('menu')
            seq = result['seq']
            if self.epoch != result['epoch']:
                # Offline input was deliberately discarded by the MCU.
                self.epoch = result['epoch']
                self.ack = seq
                self.last_tick = self.last_direction = None
            for offset in range(0, len(data), 5):
                event_seq = (seq + offset // 5) & 0xffffffff
                if event_seq != self.ack:
                    # Retry replies may contain already delivered entries.
                    if ((self.ack - event_seq) & 0xffffffff) < 0x80000000:
                        continue
                    raise ValueError('Panel event sequence gap')
                action, tick = struct.unpack_from('<BI', data, offset)
                age = ((result['tick'] - tick) & 0xffffffff) * .0005
                event_at = received - age
                if action in (1, 2):
                    direction = action ^ (3 if self.reverse else 0)
                    key = 'up' if direction == 1 else 'down'
                    if (self.last_direction == direction and self.last_tick is not None
                        and ((tick - self.last_tick) & 0xffffffff) * .0005 <= self.fast_rate):
                        key = 'fast_' + key
                    self.last_tick, self.last_direction = tick, direction
                elif action in (3, 4):
                    key = 'click' if action == 3 else 'long_click'
                else:
                    raise ValueError('Unknown panel input event')
                menu.key_event(key, event_at)
                self.ack = (self.ack + 1) & 0xffffffff
        except Exception as exc:
            self.stop()
            self.printer.invoke_shutdown('Malevich panel: %s' % (exc,))
            return self.reactor.NEVER
        return received + (.001 if len(data) == 40 else .020)

    def cmd_status(self, gcmd):
        self.stats = self.status_cmd.send([])
        r = self.stats
        gcmd.respond_info('HC165 raw=0x%02x online=%d menu=%d overflow=%d '
                         'invalid=%d max_scan_ticks=%d' % tuple(
            r[k] for k in ('raw', 'online', 'visible', 'overflow',
                          'invalid', 'max_scan_ticks')))
