"""Build the native Windows SDR++ module with MSVC and the target portable DLLs.

No deployment outside the project. Prepare the pinned SDR++ source and local
MSVC first; see host/sdrpp/README.md. --runtime creates an isolated test copy.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from sdr.rf_catalog import catalog


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdrpp-root',type=Path,default=Path('D:/Tools/sdrpp_windows_x64'))
    parser.add_argument('--runtime',action='store_true')
    parser.add_argument('--runtime-dir',type=Path,default=ROOT/'work/sdrpp/runtime')
    parser.add_argument('--host-dir',type=Path,default=ROOT/'outputs/host/windows')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'outputs/host/sdrpp')
    parser.add_argument('--build-dir',type=Path,default=ROOT/'work/sdrpp/build')
    args=parser.parse_args()
    host=args.host_dir.resolve();out=args.output_dir.resolve();build=args.build_dir.resolve()
    if not host.is_relative_to(ROOT/'outputs/host') or not out.is_relative_to(ROOT/'outputs/host') or not build.is_relative_to(ROOT/'work'):
        parser.error('host/output must be inside outputs/host and build must be inside work')
    area=ROOT/'work/sdrpp';sdk=area/'source/core/src'
    build.mkdir(parents=True,exist_ok=True);out.mkdir(parents=True,exist_ok=True)
    compiler=sorted((area/'msvc/VC/Tools/MSVC').glob('*/bin/Hostx64/x64/cl.exe'))[-1]
    vc=compiler.parents[3];kits=area/'msvc/Windows Kits/10'
    version=sorted((kits/'Include').iterdir())[-1].name
    env=dict(os.environ)
    env['PATH']=str(compiler.parent)+os.pathsep+str(kits/'bin'/version/'x64')+os.pathsep+env.get('PATH','')
    env['INCLUDE']=os.pathsep.join(map(str,[vc/'include',kits/'Include'/version/'ucrt',kits/'Include'/version/'shared',kits/'Include'/version/'um']))
    env['LIB']=os.pathsep.join(map(str,[vc/'lib/x64',kits/'Lib'/version/'ucrt/x64',kits/'Lib'/version/'um/x64']))
    lib=compiler.with_name('lib.exe');dumpbin=compiler.with_name('dumpbin.exe')
    def run(command):
        p=subprocess.run(list(map(str,command)),env=env,cwd=build,text=True,errors='replace',
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        if p.returncode:
            print(p.stdout);raise RuntimeError('Build command failed: '+str(command[0]))
        return p.stdout
    for dll in ['sdrpp_core','volk','sdr_usb']:
        source=(host/'sdr_usb.dll') if dll=='sdr_usb' else args.sdrpp_root/(dll+'.dll')
        shutil.copy2(source,build/(dll+'.dll'))
        exports=run([dumpbin,'/nologo','/exports',build/(dll+'.dll')])
        names=re.findall(r'^\s*\d+\s+[0-9A-F]+\s+[0-9A-F]+\s+(\S+)',exports,re.M)
        if not names:raise RuntimeError('No DLL exports: '+dll)
        definition=build/(dll+'.def')
        definition.write_text('LIBRARY '+dll+'\nEXPORTS\n'+'\n'.join(n+(' DATA' if n in ('sourceManager','args') else '') for n in names)+'\n')
        print(run([lib,'/nologo','/machine:x64','/def:'+str(definition),'/out:'+str(build/(dll+'.lib'))]))
    header='#pragma once\n#include <cstdint>\nstruct Route {uint32_t band,low,high,center;};\nstatic const Route routes[]={\n'
    for row in catalog()['rows']:
        if not row['software_integrated']:continue
        p=row['software_profile'];center=p['anchor_first_hz']
        if p['anchor_policy']!='fixed':center=((p['minimum_hz']+p['maximum_hz'])//200000)*100000
        header+='{%d,%du,%du,%du},\n'%(row['raw_band_id'],p['minimum_hz'],p['maximum_hz'],center)
    (build/'routes.hpp').write_text(header+'};\n')
    command=[compiler,'/nologo','/std:c++17','/EHsc','/O2','/MD','/W4','/LD',
        '/I'+str(sdk),'/I'+str(sdk/'imgui'),'/I'+str(ROOT/'host/sdrpp/sdk'),'/I'+str(build),
        ROOT/'host/sdrpp/main.cpp','/link','/LIBPATH:'+str(build),'sdrpp_core.lib','volk.lib','sdr_usb.lib',
        '/OUT:'+str(out/'uis8910_source.dll')]
    print(run(command))
    print(run([compiler,'/nologo','/std:c++17','/EHsc','/O2','/MD',
        ROOT/'tools/verify/soapy_queue_harness.cpp','/Fe:'+str(build/'queue-test.exe')]))
    print(run([build/'queue-test.exe']))
    print(run([compiler,'/nologo','/std:c++17','/EHsc','/O2','/MD','/I'+str(build),
        ROOT/'tools/verify/rf_auto_harness.cpp','/Fe:'+str(build/'rf-auto-test.exe')]))
    print(run([build/'rf-auto-test.exe']))
    print(run([compiler,'/nologo','/std:c++17','/EHsc','/O2','/MD',
        '/I'+str(sdk),'/I'+str(ROOT/'host/sdrpp/sdk'),
        ROOT/'tools/verify/sdrpp_fft_harness.cpp','/link','/LIBPATH:'+str(build),'volk.lib',
        '/OUT:'+str(build/'fft-test.exe')]))
    # Run against the real portable core and its existing DLL dependencies.
    env['PATH']=str(args.sdrpp_root)+os.pathsep+env['PATH']
    fft_test=json.loads(run([build/'fft-test.exe']).strip())
    shutil.copy2(host/'sdr_usb.dll',out/'sdr_usb.dll')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=area/'source',text=True).strip()
    dependencies=[ROOT/'host/sdrpp/main.cpp',ROOT/'host/sdrpp/CoreFft.hpp',ROOT/'tools/verify/sdrpp_fft_harness.cpp',ROOT/'host/common/RfAuto.hpp',ROOT/'host/common/rf_auto.h',ROOT/'firmware/sdr_receiver/sample_rate.h',ROOT/'tools/verify/rf_auto_harness.cpp',ROOT/'host/soapy/RxQueue.hpp',ROOT/'host/sdrpp/sdk/volk/volk.h',
        Path(__file__),build/'routes.hpp',ROOT/'firmware/capture/rxcapt_profile.c',ROOT/'tools/sdr/rf_catalog.py',
        host/'sdr_usb.dll',build/'sdrpp_core.dll',build/'volk.dll',
        sdk/'module.h',sdk/'dsp/stream.h',sdk/'dsp/types.h',sdk/'signal_path/source.h',sdk/'imgui/imgui.h']
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    report=dict(status='built',device_accessed=False,hardware_tested=False,sdrpp_commit=commit,
        offline_tests=['IQ queue/format harness','Auto route boundary, unavailable candidate, overlap and30000 request-grid checks'],
        real_core_fft_test=fft_test,
        compiler=str(compiler.relative_to(ROOT)),windows_sdk=version,
        target_sdrpp_core_sha256=sha(args.sdrpp_root/'sdrpp_core.dll'),
        dependencies={p.relative_to(ROOT).as_posix():sha(p) for p in dependencies},
        artifacts=[dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p),bytes=p.stat().st_size)
            for p in [out/'uis8910_source.dll',out/'sdr_usb.dll']])
    (out/'build.json').write_text(json.dumps(report,indent=2)+'\n')
    if args.runtime:
        runtime=args.runtime_dir.resolve()
        if not runtime.is_relative_to(ROOT/'work'):
            parser.error('runtime must be inside work')
        shutil.copytree(args.sdrpp_root,runtime,dirs_exist_ok=True)
        shutil.copy2(out/'uis8910_source.dll',runtime/'modules/uis8910_source.dll')
        shutil.copy2(out/'sdr_usb.dll',runtime/'sdr_usb.dll')
        cfg=json.loads((runtime/'config.json').read_text(encoding='utf-8'))
        cfg['moduleInstances']['UIS8910 Source']=dict(enabled=True,module='uis8910_source')
        cfg.update(source='UIS8910',frequency=881500000.0,windowSize=dict(w=1280,h=850),maximized=False)
        (runtime/'config.json').write_text(json.dumps(cfg,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
