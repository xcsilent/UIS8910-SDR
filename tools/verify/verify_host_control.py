"""Build/run Windows control-code harness against reference monitor frames.

Only the COM read/write/clock calls are stubbed. No device access. Python's
existing monitor codec supplies independent wire vectors and expectations.
"""
import hashlib,json,os,struct,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/debug'))
from uis_debug import frame


def main():
    cross=ROOT/'work/windows-toolchain/root/usr'
    environment=dict(os.environ)
    environment['PATH']=str(cross/'bin')+os.pathsep+environment.get('PATH','')
    build=ROOT/'work/host-control-test';build.mkdir(exist_ok=True)
    source=ROOT/'tools/verify/host_control_harness.c'
    exe=build/'control_test.exe'
    subprocess.run([str(cross/'bin/x86_64-w64-mingw32-gcc-posix'),'-std=c11','-O2',
        '-Wall','-Wextra','-Werror','-static-libgcc',str(source),'-o',str(exe)],env=environment,check=True)
    words=[0]*48;words[0:2]=[0x31574353,1];words[22]=8000;words[47]=881600000
    recovery=[0]*24;recovery[0:2]=[0x31524353,1];recovery[4]=2
    info=b'{"protocol":1}'
    cases=[(1,1,b'',info,0),(2,47,struct.pack('<4I',1,5,881600000,20),b'',0),
        (3,45,struct.pack('<4I',1,1000,0,0),struct.pack('<I',7),0),
        (4,44,b'',struct.pack('<48I',*words),0),(5,48,b'',struct.pack('<24I',*recovery),0),
        (6,46,b'',b'',0),(7,1,b'',None,0),(8,1,b'',b'',5),
        (9,1,b'',info,0),(10,1,b'',info,0),(11,2,b'',None,0),(12,43,b'',None,0),
        (13,47,struct.pack('<5I',2,5,881600000,20,1),b'',0),
        (14,45,struct.pack('<4I',1,0,0,0),struct.pack('<I',7),0),(15,49,b'',b'',0),
        (16,1,b'',info,0),(17,47,struct.pack('<5I',2,5,881600000,20,2),b'',0)]
    with tempfile.TemporaryDirectory(dir=build) as temporary:
        directory=Path(temporary)
        windows=subprocess.check_output(['wslpath','-w',str(directory)],text=True).strip()
        for mode,op,payload,body,status in cases:
            wire=frame(op|0x80,0x1235,body,status) if body is not None else b''
            if mode==9:
                corrupt=bytearray(wire);corrupt[-1]^=1
                oversized=b'UDG1\x01\x81\x01\x10'+bytes(12)
                bad_version=b'UDG1\x02\x81'+bytes(14)
                wire=(b'noiseUD'+oversized+bad_version+frame(op|0x80,0x9999,b'stale')+
                      frame(0xc8,0x1235,b'wrong op')+bytes(corrupt)+wire)
            (directory/'response.bin').write_bytes(wire)
            (directory/'request.bin').write_bytes(frame(op,0x1235,payload))
            result=subprocess.run([str(exe),str(mode),windows+'\\response.bin',windows+'\\request.bin'],
                capture_output=True,text=True,timeout=10)
            if result.returncode:
                raise AssertionError(f'control case{mode}: {result.stdout}\n{result.stderr}')
    # Confirm the same DLL exposes both control and data; no COM open here.
    dll=ROOT/'outputs/host/windows/sdr_usb.dll'
    dll_windows=subprocess.check_output(['wslpath','-w',str(dll)],text=True).strip()
    # Native Python is available through Windows interop, unlike ctypes in WSL.
    python='/mnt/c/Program Files/Python314/python.exe'
    command='import ctypes; d=ctypes.CDLL('+repr(dll_windows)+'); '+ ';'.join(
        'assert getattr(d,'+repr(name)+')' for name in ('sdr_usb_receive_controlled','sdr_control_open',
        'sdr_control_request','sdr_control_configure','sdr_control_start','sdr_control_stop',
        'sdr_control_status','sdr_control_recovery'))
    subprocess.run([python,'-B','-c',command],check=True)
    dependencies=[Path(__file__),source,ROOT/'host/windows/sdr_control.c',ROOT/'host/windows/sdr_control.h',
                  ROOT/'tools/debug/uis_debug.py',ROOT/'tools/usb/native_control.py',dll]
    report=dict(status='passed',device_accessed=False,hardware_tested=False,
        scope='native Windows C control decoder and typed API with stub COM/clock, Python reference frames; DLL exports checked, no physical serial timing or firmware proof',
        tests=['partial writes and fragmented reads','INFO frame matches independent Python codec',
            'configure/start/stop/status/recovery operations and binary layouts',
            'stale transaction, wrong operation, corrupted CRC and noise resynchronization',
            'three timeout retries preserve exact sequence and bytes',
            'nonblocking empty reads yield1ms then accept fragmented response without resending',
            'device BUSY retained separately from Win32 errors','undersized response buffer rejected',
            'generic memory operation rejected without I/O','control and data exports coexist in native DLL'],
        cases=len(cases),dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies})
    (ROOT/'records/usb/host-control-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
