"""Transport-level tests; no MCU or printer required."""
import importlib.util
from pathlib import Path
import struct
import sys
import types
import unittest

pkg = types.ModuleType('panel_test')
pkg.__path__ = []
sys.modules['panel_test'] = pkg
uc = types.ModuleType('panel_test.uc1701')
uc.DisplayBase = object
uc.BACKGROUND_PRIORITY_CLOCK = 0x7fffffff00000000
sys.modules[uc.__name__] = uc
spec = importlib.util.spec_from_file_location('panel_test.driver',
    Path(__file__).resolve().parents[1] / 'host/malevich_panel.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class HostTests(unittest.TestCase):
    def panel(self):
        p = object.__new__(mod.MalevichPanel)
        p.running = True
        p.epoch = 1
        p.ack = 0
        p.reverse = False
        p.fast_rate = .03
        p.last_tick = p.last_direction = None
        p.poll_timer = None
        p.reactor = types.SimpleNamespace(monotonic=lambda:100., NEVER=9999.,
                                         update_timer=lambda *a:None)
        p.received = []
        p.errors = []
        menu = types.SimpleNamespace(key_event=lambda *a:p.received.append(a))
        p.printer = types.SimpleNamespace(lookup_object=lambda name:menu,
                                         invoke_shutdown=p.errors.append)
        return p
    def reply(self,p,seq,events,now=200):
        r=dict(epoch=1,seq=seq,tick=now,data=b''.join(struct.pack('<BI',*e) for e in events))
        p.query_cmd=types.SimpleNamespace(send=lambda args:r)
        return p.poll(100.)
    def test_order_retry_timestamps(self):
        p=self.panel()
        self.reply(p,0,[(1,100),(1,110),(2,120),(3,130),(4,140)])
        self.assertEqual([e[0] for e in p.received],['up','fast_up','down','click','long_click'])
        self.assertAlmostEqual(p.received[0][1],99.95)
        self.reply(p,0,[(1,100),(1,110),(2,120),(3,130),(4,140)])
        self.assertEqual(len(p.received),5)
        self.assertFalse(p.errors)
    def test_reverse_and_wrap(self):
        p=self.panel();p.reverse=True;p.ack=0xffffffff
        self.reply(p,0xffffffff,[(1,0xfffffff0),(2,10)],now=20)
        self.assertEqual(p.ack,1)
        self.assertEqual([e[0] for e in p.received],['down','up'])
        self.assertLess(p.received[0][1],p.received[1][1])
    def test_gap_stops(self):
        p=self.panel();self.reply(p,1,[(1,100)])
        self.assertFalse(p.running);self.assertTrue(p.errors)
    def test_backlog_drains(self):
        p=self.panel();n=self.reply(p,0,[(1,100+i) for i in range(8)])
        self.assertEqual(n,100.001);self.assertEqual(p.ack,8)
    def test_epoch_resync(self):
        p=self.panel();p.epoch=0
        self.reply(p,10,[(1,100)])
        self.assertEqual(p.ack,11);self.assertFalse(p.errors)
    def test_framebuffer_chunks(self):
        p=self.panel();p.vram=[bytearray(128) for _ in range(8)];p.sent=[None]*32
        sent=[];p.frame_cmd=types.SimpleNamespace(send=lambda *a,**kw:sent.append(a))
        p.flush();self.assertEqual(len(sent),32)
        p.flush();self.assertEqual(len(sent),32)
        p.vram[7][127]=255;p.flush()
        self.assertEqual(len(sent),33);self.assertEqual(sent[-1][0][0],992)
        self.assertEqual(sent[-1][0][1][-1],255)

if __name__=='__main__':unittest.main()
