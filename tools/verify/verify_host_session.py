"""Native Windows session threads with fake control/USB, no hardware access."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'records/usb/host-session-verification.json')
    args=parser.parse_args()
    cross=ROOT/'work/windows-toolchain/root/usr'
    env=dict(os.environ);env['PATH']=str(cross/'bin')+os.pathsep+env.get('PATH','')
    build=ROOT/'work/host-session-test';build.mkdir(exist_ok=True)
    sources=[ROOT/'host/windows/sdr_session.c',ROOT/'host/windows/sdr_info.c',ROOT/'tools/verify/host_session_harness.c',ROOT/'firmware/capture/rxcapt_profile.c']
    exe=build/'session_test.exe'
    subprocess.run([str(cross/'bin/x86_64-w64-mingw32-gcc-posix'),'-std=c11','-O2',
        '-Wall','-Wextra','-Werror','-static-libgcc',*map(str,sources),'-o',str(exe)],env=env,check=True)
    subprocess.run([str(exe)],check=True,timeout=20)
    dependencies=sources+[Path(__file__),ROOT/'host/windows/sdr_session.h',ROOT/'host/windows/sdr_control.h',ROOT/'host/windows/sdr_bandwidth.h',ROOT/'host/common/rf_auto.h',ROOT/'firmware/capture/rxcapt_profile.h']
    report=dict(status='passed',device_accessed=False,hardware_tested=False,
        scope='Windows threads/events; fake control and USB, not physical drain or RF validation',
        tests=['ready precedes START on separate thread','finite self-drain still explicitly STOPs the held service lease before success',
               'consumer stop issues STOP while reads continue, consumer called once',
               'initial USB failure never starts device','uncertain START attempts STOP and preserves error',
               'unsupported INFO rejected before configuration or START',
               'BW1 advertised configuration succeeds; legacy capability or wrong BW/rate readback refuses START',
               'BW2 continuous session configures and drains; BW0/BW1-only INFO rejects BW2 before configuration or START',
               'steady counters exclude warmup/tail and recover exact synthetic rate; counter reset invalidates measurement',
               'until-STOP consumer cancellation drains; missing capability refuses START; lease failure requests STOP; unexpected producer terminal is an error'],
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies})
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
