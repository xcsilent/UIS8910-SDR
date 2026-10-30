"""WSL: build a Windows SoapySDR module against the project-local0.8.1 SDK."""
from pathlib import Path
import argparse,os,sys,json,hashlib,subprocess,shutil
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from sdr.rf_catalog import software_profiles
from sdr.host_toolchain import locate

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-dir',type=Path,default=ROOT/'outputs/host/windows')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'outputs/host/soapy')
    parser.add_argument('--build-dir',type=Path,default=ROOT/'work/soapy-uis8910')
    parser.add_argument('--sdk-dir',type=Path,default=ROOT/'work/soapysdr',help='prepared Soapy source/install area inside work/')
    parser.add_argument('--toolchain-root',type=Path,help='MinGW prefix; defaults to local tools, then PATH')
    args=parser.parse_args()
    host=args.host_dir.resolve();output=args.output_dir.resolve();build=args.build_dir.resolve()
    if not host.is_relative_to(ROOT/'outputs/host') or not output.is_relative_to(ROOT/'outputs/host') or not build.is_relative_to(ROOT/'work'):
        parser.error('host/output must be inside outputs/host and build must be inside work')
    sdk_area=args.sdk_dir.resolve()
    if not sdk_area.is_relative_to(ROOT/'work'):
        parser.error('Soapy SDK must be prepared inside work/')
    sdk=sdk_area/'install'
    toolchain=locate(args.toolchain_root)
    build.mkdir(parents=True,exist_ok=True)
    output.mkdir(parents=True,exist_ok=True)
    header='#pragma once\n#include <cstdint>\nstruct Route {uint32_t band,low,high,center;};\nstatic const Route routes[]={\n'
    for band,p in software_profiles().items():
        center=p['anchor_first_hz']
        if p['anchor_policy']!='fixed':center=((p['minimum_hz']+p['maximum_hz'])//200000)*100000
        header+='{%d,%du,%du,%du},\n'%(band,p['minimum_hz'],p['maximum_hz'],center)
    (build/'routes.hpp').write_text(header+'};\n')
    env=toolchain.env
    compiler=toolchain.cxx
    command=[str(compiler),'-std=c++14','-O2','-Wall','-Wextra','-Werror','-static-libgcc','-static-libstdc++',
       '-shared',str(ROOT/'host/soapy/UIS8910.cpp'),'-I'+str(build),'-I'+str(sdk/'include'),
       '-L'+str(sdk/'lib'),'-L'+str(host),'-lSoapySDR','-lsdr_usb',
       '-o',str(output/'uis8910Support.dll')]
    subprocess.run(command,env=env,check=True)
    common=[str(compiler),'-std=c++14','-O2','-Wall','-Wextra','-Werror','-static-libgcc','-static-libstdc++']
    subprocess.run(common+[str(ROOT/'tools/verify/soapy_queue_harness.cpp'),'-o',str(build/'queue-test.exe')],env=env,check=True)
    subprocess.run(common+[str(ROOT/'tools/verify/soapy_hardware_probe.cpp'),'-I'+str(sdk/'include'),'-L'+str(sdk/'lib'),
        '-lSoapySDR','-o',str(output/'soapy_receive_probe.exe')],env=env,check=True)
    for name in ['libSoapySDR.dll','SoapySDRUtil.exe']:shutil.copy2(sdk/'bin'/name,output/name)
    shutil.copy2(host/'sdr_usb.dll',output/'sdr_usb.dll')
    shutil.copy2(toolchain.runtime('libwinpthread-1.dll'),output/'libwinpthread-1.dll')
    shutil.copy2(sdk_area/'source/LICENSE_1_0.txt',output/'SoapySDR-LICENSE.txt')
    sources=[Path(__file__),ROOT/'host/soapy/UIS8910.cpp',ROOT/'host/soapy/RxQueue.hpp',ROOT/'host/common/RfAuto.hpp',ROOT/'host/common/rf_auto.h',ROOT/'firmware/sdr_receiver/sample_rate.h',
        ROOT/'tools/verify/soapy_queue_harness.cpp',ROOT/'tools/verify/soapy_hardware_probe.cpp',
        ROOT/'tools/usb/prepare_soapy_sdk.py',sdk/'bin/libSoapySDR.dll',
        ROOT/'firmware/capture/rxcapt_profile.c',ROOT/'tools/sdr/rf_catalog.py',build/'routes.hpp',
        host/'sdr_usb.dll',sdk_area/'source.json',ROOT/'tools/sdr/host_toolchain.py']
    report=dict(status='built',device_accessed=False,hardware_tested=False,toolchain=toolchain.validate(),
      soapy_source=json.loads((sdk_area/'source.json').read_text()),
      dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
      artifacts=[dict(path=p.relative_to(ROOT).as_posix(),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in output.glob('*') if p.is_file() and p.name!='build.json'])
    (output/'build.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
