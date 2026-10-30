"""WSL builds and runs a native Windows harness with stub WinUSB calls."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]

def main():
    cross=ROOT/'work/windows-toolchain/root/usr'
    build=ROOT/'work/host-receive-review'
    build.mkdir(parents=True,exist_ok=True)
    source=ROOT/'tools/verify/host_receive_harness.c'
    exe=build/'host_receive_harness.exe'
    environment=dict(os.environ)
    environment['PATH']=str(cross/'bin')+os.pathsep+environment.get('PATH','')
    subprocess.run([str(cross/'bin/x86_64-w64-mingw32-gcc-posix'),'-std=c11','-O2','-Wall','-Wextra',
        '-Werror','-static-libgcc',str(source),'-o',str(exe),'-lwinusb','-lsetupapi'],env=environment,check=True)
    result=subprocess.check_output([str(exe)],text=True).strip()
    dependencies=[source,ROOT/'host/windows/sdr_usb.c',ROOT/'host/windows/sdr_usb.h',Path(__file__)]
    report=dict(status='passed',device_accessed=False,hardware_tested=False,result=result,
        scope='initial readiness, explicit-stop read beyond simulated200s, zero-duration callback requirement, consumer/external stop, successful-tail order and cancellation; no physical duration or bounded driver cancellation proof',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies})
    (ROOT/'records/usb/host-receive-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    main()
