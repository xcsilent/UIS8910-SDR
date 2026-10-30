"""Build native Windows raw USB DLL/CLI using a project-local MinGW toolchain.

Run with WSL Python after tools/usb/prepare_host_toolchain.py. No device access.
"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import subprocess
from sdr.rf_catalog import validate_b3_floor
from sdr.host_toolchain import locate

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain-root',type=Path,help='MinGW prefix, e.g. /usr; defaults to retained local tools, then PATH')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'outputs/host/windows')
    parser.add_argument('--experimental-b3-min-hz',type=int,help='manual B3 experiment floor; Auto retains its delivered lower bound')
    parser.add_argument('--unrestricted-frequency',action='store_true',help='remove manual-route frequency envelopes; uint32 Hz/100 Hz format remains')
    args=parser.parse_args()
    toolchain=locate(args.toolchain_root,cpp=False)
    gcc=toolchain.cc
    if args.unrestricted_frequency and args.experimental_b3_min_hz is not None:
        parser.error('choose unrestricted frequency or bounded B3 experiment')
    validate_b3_floor(args.experimental_b3_min_hz)
    output=args.output_dir.resolve()
    if not output.is_relative_to(ROOT/'outputs/host'):
        parser.error('host output must be inside outputs/host')
    if (args.experimental_b3_min_hz is not None or args.unrestricted_frequency) and (output==ROOT/'outputs/host/windows' or output.exists()):
        parser.error('B3 experiment requires a new independent host output directory')
    output.mkdir(parents=True,exist_ok=True)
    source=ROOT/'host/windows'
    common=[str(gcc),'-std=c11','-O2','-Wall','-Wextra','-Werror','-static-libgcc']
    if args.experimental_b3_min_hz is not None:
        common.append('-DRXCAPT_EXPERIMENTAL_B3_MIN_RAW='+str(args.experimental_b3_min_hz//100)+'u')
    if args.unrestricted_frequency:
        common.append('-DRXCAPT_UNRESTRICTED_FREQUENCY=1')
    environment=toolchain.env
    commands=[common+['-shared',str(source/'sdr_usb.c'),str(source/'sdr_control.c'),str(source/'sdr_session.c'),str(source/'sdr_info.c'),str(ROOT/'firmware/capture/rxcapt_profile.c'),'-o',str(output/'sdr_usb.dll'),
        '-Wl,--out-implib,'+str(output/'libsdr_usb.a'),'-Wl,--export-all-symbols','-lwinusb','-lsetupapi'],
        common+[str(source/'sdr_receive.c'),str(source/'file_sink.c'),'-o',str(output/'sdr_receive.exe'),
        '-L'+str(output),'-lsdr_usb']]
    for command in commands:
        subprocess.run(command,cwd=ROOT,env=environment,check=True)
    artifacts=[]
    for name in ('sdr_usb.dll','sdr_receive.exe','libsdr_usb.a'):
        path=output/name
        artifacts.append(dict(path=path.relative_to(ROOT).as_posix(),bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    report=dict(status='built',device_accessed=False,hardware_tested=False,artifacts=artifacts,
        toolchain=toolchain.validate(cpp=False),
        experimental_b3_min_hz=args.experimental_b3_min_hz,unrestricted_frequency=args.unrestricted_frequency,
        sources={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in list(source.glob('*.[ch]'))+[Path(__file__),ROOT/'tools/sdr/host_toolchain.py',ROOT/'host/common/rf_auto.h',ROOT/'firmware/capture/rxcapt_profile.c',ROOT/'firmware/capture/rxcapt_profile.h',ROOT/'firmware/sdr_receiver/sample_rate.h']})
    (output/'build.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
