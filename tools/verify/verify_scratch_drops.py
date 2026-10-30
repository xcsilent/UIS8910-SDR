"""Check control capability gate and decoding without touching hardware."""
import hashlib
import json
from pathlib import Path
import struct
import sys

root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'tools'))
from sdr.scratch_drops import transact

class Client:
    def __init__(self,info,data=b''):
        self._info=info;self.data=data;self.calls=[]
    def info(self):return self._info
    def request(self,op):self.calls.append(op);return self.data

base={'firmware':'uis8910-sdr-bw0-usb-v1'}
for info in (base,dict(base,bw0_scratch_drops_operation=52,bw0_scratch_drops_abi=2),
             {'firmware':'other','bw0_scratch_drops_operation':52,'bw0_scratch_drops_abi':1}):
    c=Client(info);report={'operation_sent':False}
    try:transact(c,report);raise AssertionError('gate accepted unsupported firmware')
    except ValueError:assert not c.calls and not report['operation_sent']
supported=dict(base,bw0_scratch_drops_operation=52,bw0_scratch_drops_abi=1)
for data in (b'',struct.pack('<4I',0,1,9,7),struct.pack('<4I',0x31504453,1,0,7)):
    try:transact(Client(supported,data),{});raise AssertionError('invalid reply accepted')
    except ValueError:pass
report={};c=Client(supported,struct.pack('<4I',0x31504453,1,9,0xffffffff));transact(c,report)
assert c.calls==[52] and report['epoch']==9 and report['counter_saturated'] and not report['exact_lost_samples_known']
paths=[Path(__file__),root/'tools/sdr/scratch_drops.py',root/'firmware/debug_monitor/ap_monitor.c',root/'firmware/sdr_receiver/bw0_usb_service.c']
result={'status':'passed','device_accessed':False,'scope':'Fake control client, ABI and capability gating; no hardware or AP control execution.',
        'dependencies':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
(root/'records/usb/geometry-scratch-control-host.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
print(json.dumps(result,indent=2))
