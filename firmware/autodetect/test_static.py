#!/usr/bin/env python3
"""Static safety checks only. NOT a substitute for physical board tests."""
from pathlib import Path
import base64
import hashlib
import struct
import re

root=Path(__file__).resolve().parent
src=(root/'autodetect.c').read_text()
binary=root/'autodetect.bin'
b=(binary.read_bytes() if binary.is_file()
   else base64.b64decode((root/'autodetect.bin.b64').read_bytes()))
assert 512 <= len(b) < 512*1024
sp, pc=struct.unpack_from('<II',b)
assert sp==0x20020000, hex(sp)
assert 0x08000001 <= pc < 0x08080000 and pc & 1,hex(pc)
assert len(b)>1000 and b'AutoDetect v0.6.0' in b
print('PASS Cortex-M4 vector, flash base, data section')
assert '#define USART3 0x40004800u' in src
assert '#define UART5  0x40005000u' in src
assert 'gpio_set(GPIOB,10,GPIO_AF,1,PULL_UP,7u)' in src
assert 'gpio_set(GPIOB,10,GPIO_OUT,1,PULL_UP,0)' in src
assert 'pin_write(GPIOE,14,1u)' in src
assert not re.search(r'pin_write\(GPIOE,\s*14\s*,\s*0u?\s*\)',src)
assert 'gpio_set(GPIOE,14,GPIO_IN' in src
assert 'POWER_MAX_US 45000000u' in src
print('PASS pins: PB10 always open-drain if output; PE14 HIGH or input only')
for token in ('{4,3,2,1,5,6,7}', '{1,1,1,1,0,0,0}', '{0,1,2,3,0,1,3}',
              '0x06u', '0x04u', '0x21u', '0x11u'):
    assert token in src,token
assert 'c->second==c->third' in src
assert 'a->ioin==b->ioin' in src
assert 'bytes[7]==crc_tmc(bytes,7u)' in src
print('PASS expected UART bank/address mapping and TMC identification checks')
# CRC implementation cross-check against known TMC UART frame structure.
def crc(frame):
    val=0
    for byte in frame:
        for bit in range(8):
            x=((val>>7)^(byte>>bit))&1
            val=((val<<1)^(7 if x else 0))&0xff
    return val
assert crc([5,0,6])==0x6f
assert crc([5,1,6])==0xd9
assert crc([5,0xff,6,0x21,0,0,0xc0])==0x48
print('PASS TMC2209 CRC known-frame vectors')
line=(root/'autodetect.bin.sha256').read_text().strip().split()[0]
assert hashlib.sha256(b).hexdigest()==line
print('PASS BIN SHA256')
print('ALL STATIC CHECKS PASSED; hardware behavior NOT validated')
