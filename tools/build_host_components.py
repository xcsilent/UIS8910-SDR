"""WSL/Linux: prepare and build the Windows x64 library, CLI and Soapy module.

Fresh source-tree entry point. Uses Python's standard library, POSIX MinGW C/C++,
CMake and Ninja. Preserves deployed host manifests and existing local SDKs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from sdr.host_toolchain import locate

ROOT=Path(__file__).resolve().parents[1]
SYSTEM_DLLS={n.lower()+'.dll' for n in ['kernel32','kernelbase','msvcrt','advapi32','user32',
    'gdi32','shell32','ole32','oleaut32','comdlg32','comctl32','setupapi','winusb','ws2_32',
    'rpcrt4','ntdll','shlwapi','version','bcrypt','ucrtbase','cfgmgr32','secur32','imm32']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'outputs/host/build-v0.1')
    parser.add_argument('--build-dir',type=Path,default=ROOT/'work/wsl-host-v0.1')
    parser.add_argument('--toolchain-root',type=Path,help='explicit MinGW prefix, e.g. /usr')
    parser.add_argument('--package-dir',type=Path,help='optional offline distro-matched MinGW .deb cache')
    parser.add_argument('--jobs',type=int,default=3)
    parser.add_argument('--without-soapy',action='store_true',help='only Windows DLL/CLI and timing CLI; no CMake/Ninja needed')
    args=parser.parse_args()
    if sys.platform!='linux' or platform.machine() not in ('x86_64','amd64'):
        parser.error('use x86_64 Linux Python3 in WSL/Ubuntu; see docs/building-wsl.md')
    if not 1<=args.jobs<=64:
        parser.error('--jobs must be in 1..64')
    if args.package_dir and args.toolchain_root:
        parser.error('choose --package-dir or --toolchain-root')
    output,build=args.output_dir.resolve(),args.build_dir.resolve()
    if (not output.is_relative_to(ROOT/'outputs/host') or output==ROOT/'outputs/host'
            or not build.is_relative_to(ROOT/'work') or build==ROOT/'work'
            or output.exists() or build.exists()):
        parser.error('choose new output/build directories inside outputs/host and work')
    if not args.without_soapy:
        for tool in ['cmake','ninja']:
            if not shutil.which(tool):
                parser.error('missing '+tool+'; see docs/building-wsl.md')
    build.mkdir(parents=True)
    log=build/'build.log'
    commands=[]

    def run(stage,command):
        command=list(map(str,command))
        print(stage,flush=True)
        commands.append(dict(stage=stage,command=command))
        with log.open('a',encoding='utf-8') as stream:
            stream.write(stage+'\n'+repr(command)+'\n')
            stream.flush()
            result=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        if result.returncode:
            print(log.read_text(encoding='utf-8',errors='replace')[-7000:],file=sys.stderr)
            raise subprocess.CalledProcessError(result.returncode,command)

    prepare=[sys.executable,'-B',ROOT/'tools/usb/prepare_host_toolchain.py']
    if args.toolchain_root:
        prepare+=['--toolchain-root',args.toolchain_root]
    if args.package_dir:
        prepare+=['--package-dir',args.package_dir]
    run('Prepare MinGW C/C++ toolchain (existing local tools, system tools, or apt cache)',prepare)
    # An explicit offline cache selects its extracted prefix even when the
    # caller has configured a different default toolchain through the environment.
    toolchain=locate(ROOT/'work/windows-toolchain/root/usr' if args.package_dir else args.toolchain_root)
    common=['--toolchain-root',str(toolchain.root)]
    run('Build Windows receive DLL and CLI',
        [sys.executable,'-B',ROOT/'tools/build_host.py','--output-dir',output/'windows',
         '--unrestricted-frequency',*common])
    run('Build timing CLI',
        [sys.executable,'-B',ROOT/'tools/build_tune_benchmark.py','--host-dir',output/'windows',
         '--output-dir',output/'tune',*common])
    if not args.without_soapy:
        area=build/'soapysdr'
        run('Build bundled SoapySDR0.8.1 for Windows',
            [sys.executable,'-B',ROOT/'tools/usb/prepare_soapy_sdk.py','--area',area,
             '--jobs',str(args.jobs),*common])
        run('Build UIS8910 Soapy module and offline queue probe',
            [sys.executable,'-B',ROOT/'tools/build_soapy.py','--host-dir',output/'windows',
             '--output-dir',output/'soapy','--build-dir',build/'soapy-module',
             '--sdk-dir',area,*common])
    # Check PE architecture and runtime closure independently of successful
    # linking. This doesn't execute Windows code or open any device.
    closure=[]
    artifacts=[]
    for path in sorted(output.rglob('*')):
        if not path.is_file() or path.name.endswith('.json'):
            continue
        if path.suffix.lower() in ('.dll','.exe'):
            output_text=subprocess.check_output([str(toolchain.objdump),'-p',str(path)],text=True)
            if 'pei-x86-64' not in output_text:
                raise ValueError('not a Windows x64 PE: '+str(path))
            imports=re.findall(r'DLL Name:\s*(\S+)',output_text)
            available={p.name.lower() for p in path.parent.iterdir() if p.is_file()}
            missing=[n for n in imports if n.lower() not in SYSTEM_DLLS
                     and not n.lower().startswith(('api-ms-win-','ext-ms-win-'))
                     and n.lower() not in available]
            if missing:
                raise ValueError('missing Windows runtime next to '+str(path)+': '+', '.join(missing))
            closure.append(dict(path=path.relative_to(ROOT).as_posix(),imports=imports,missing=[]))
        artifacts.append(dict(path=path.relative_to(ROOT).as_posix(),bytes=path.stat().st_size,
                              sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    scripts=[Path(__file__),ROOT/'tools/sdr/host_toolchain.py',ROOT/'tools/build_host.py',
             ROOT/'tools/build_soapy.py',ROOT/'tools/build_tune_benchmark.py',
             ROOT/'tools/usb/prepare_host_toolchain.py',ROOT/'tools/usb/prepare_soapy_sdk.py',
             ROOT/'build-support/host-manifest.json',ROOT/'firmware/capture/rxcapt_profile.c']
    result=dict(status='built_not_promoted',device_accessed=False,hardware_tested=False,
        release_version=(ROOT/'VERSION').read_text().strip(),build_platform=platform.platform(),
        toolchain=toolchain.validate(),soapy_included=not args.without_soapy,
        output_directory=output.relative_to(ROOT).as_posix(),build_directory=build.relative_to(ROOT).as_posix(),
        artifacts=artifacts,windows_import_closure=closure,
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in scripts},
        scope='Cross-compilation and PE/import checks; Windows runtime checks and hardware acceptance are separate.')
    (output/'build.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    (build/'commands.json').write_text(json.dumps(commands,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=result['status'],device_accessed=False,output=result['output_directory'],
                         artifacts=len(artifacts),windows_pe_files=len(closure)),indent=2))


if __name__=='__main__':
    main()
