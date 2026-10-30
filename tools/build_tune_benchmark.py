"""Build the latency consumer against the existing native Windows library.

WSL toolchain only; does not rebuild/deploy the DLL, firmware or SDR++ plugin.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from sdr.host_toolchain import locate

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-dir',type=Path,default=ROOT/'outputs/host/windows')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'outputs/host/tune')
    parser.add_argument('--toolchain-root',type=Path,help='MinGW prefix; defaults to local tools, then PATH')
    args=parser.parse_args()
    host=args.host_dir.resolve();directory=args.output_dir.resolve()
    if not directory.is_relative_to(ROOT/'outputs/host'):
        parser.error('output must be inside outputs/host')
    directory.mkdir(parents=True,exist_ok=True)
    toolchain=locate(args.toolchain_root,cpp=False)
    env=toolchain.env
    output=directory/'sdr_tune_benchmark.exe'
    source=ROOT/'host/windows/tune_benchmark.c'
    command=[str(toolchain.cc),'-std=c11','-O2','-Wall','-Wextra','-Werror',
        '-static-libgcc',str(source),'-L'+str(host),'-lsdr_usb','-o',str(output)]
    subprocess.run(command,env=env,check=True)
    import shutil
    if host!=directory:shutil.copy2(host/'sdr_usb.dll',directory/'sdr_usb.dll')
    paths=[source,Path(__file__),ROOT/'host/windows/sdr_session.h',ROOT/'host/windows/sdr_usb.h',
        ROOT/'host/windows/sdr_control.h',ROOT/'host/windows/sdr_bandwidth.h',
        ROOT/'firmware/sdr_receiver/sample_rate.h',host/'libsdr_usb.a',output.parent/'sdr_usb.dll']
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    report=dict(status='built',device_accessed=False,hardware_tested=False,
        dependencies={p.relative_to(ROOT).as_posix():sha(p) for p in paths},
        artifacts=[dict(path=output.relative_to(ROOT).as_posix(),sha256=sha(output),bytes=output.stat().st_size)])
    (output.parent/'tune-build.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
