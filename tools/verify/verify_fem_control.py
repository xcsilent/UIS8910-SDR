"""Exercise FEM host gating and mode readback with a mocked monitor, no hardware."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'tools/debug'))
from sdr.fem_override import configure,decode

def main():
    cases=[]
    for body in (b'',struct.pack('<4I',0,1,0,1),struct.pack('<4I',0x314d4546,2,0,1),struct.pack('<4I',0x314d4546,1,3,1)):
        try:decode(body)
        except ValueError:pass
        else:raise AssertionError('invalid reply accepted')
    class Port:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
    with tempfile.TemporaryDirectory(dir=ROOT/'work',prefix='fem-host-test-') as temporary:
        for name,value,supported,mismatch,error in (
            ('unsupported','2',False,False,False),('query',None,True,False,False),
            ('default','default',True,False,False),('value2','2',True,False,False),
            ('value5','5',True,False,False),('mismatch','2',True,True,False),
            ('busy','2',True,False,True)):
            class Client:
                calls=[]
                mode=0
                def __init__(self,*a):pass
                def info(self):
                    return dict(firmware='uis8910-sdr-bw0-usb-v1',**(dict(bw0_fem_override_operation=53,bw0_fem_override_abi=1) if supported else {}))
                def request(self,op,payload=b''):
                    self.calls.append((op,payload))
                    assert op==53
                    if payload:
                        assert len(payload)==8
                        abi,mode=struct.unpack('<2I',payload);assert abi==1
                        if error:raise RuntimeError('BUSY')
                        self.mode=0 if mismatch else mode
                    return struct.pack('<4I',0x314d4546,1,self.mode,1)
            output=Path(temporary)/(name+'.json')
            with patch('serial.Serial',Port),patch('uis_debug.Client',Client):
                report=configure(SimpleNamespace(port='MOCK',value=value,output=output))
            assert report['status']==('failed' if not supported or mismatch or error else 'passed')
            assert output.is_file()
            if not supported:assert not Client.calls
            elif value is None:assert len(Client.calls)==1
            elif error:assert len(Client.calls)==2
            else:assert len(Client.calls)==3
            cases.append(dict(case=name,status=report['status'],requests=len(Client.calls)))
    deps=[Path(__file__),ROOT/'tools/sdr/fem_override.py',ROOT/'tools/debug/uis_debug.py']
    result=dict(status='passed',device_accessed=False,cases=cases,invalid_replies_rejected=4,
        scope='Mocked host gating and protocol only; no physical RF or firmware proof.',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in deps})
    (ROOT/'records/rf/frontend-override-host-control.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
