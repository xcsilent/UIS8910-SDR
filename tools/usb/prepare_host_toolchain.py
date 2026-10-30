"""WSL/Linux: validate existing MinGW, or download it into work/ without sudo.

Prefer the retained local toolchain, then a POSIX MinGW installation on PATH.
On a fresh Ubuntu tree, packages are downloaded only when neither exists.
Use --system to check the documented apt-installed /usr toolchain explicitly.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from sdr.host_toolchain import locate

PACKAGES=['gcc-mingw-w64-x86-64-posix','g++-mingw-w64-x86-64-posix',
          'gcc-mingw-w64-x86-64-posix-runtime','gcc-mingw-w64-base',
          'binutils-mingw-w64-x86-64','mingw-w64-x86-64-dev','mingw-w64-common']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain-root',type=Path,help='explicit prefix, e.g. /usr')
    parser.add_argument('--system',action='store_true',help='validate apt-installed tools under /usr')
    parser.add_argument('--check',action='store_true',help='validate only; no download or metadata writes')
    parser.add_argument('--package-dir',type=Path,help='extract an existing offline .deb cache instead of downloading')
    args=parser.parse_args()
    if sys.platform!='linux':
        parser.error('run with Linux Python3 inside WSL/Ubuntu')
    if args.system and args.toolchain_root:
        parser.error('choose --system or --toolchain-root')
    requested=(Path('/usr') if args.system else args.toolchain_root
               or (os.environ.get('UIS8910_MINGW_ROOT') if not args.package_dir else None))
    local=ROOT/'work/windows-toolchain/root/usr'
    explicit=requested is not None
    existing=explicit or (local/'bin/x86_64-w64-mingw32-gcc-posix').exists() or shutil.which('x86_64-w64-mingw32-gcc-posix')
    if args.check or (existing and not args.package_dir):
        toolchain=locate(requested)
        package_rows=[]
    else:
        if explicit:
            parser.error('--package-dir extracts into work/windows-toolchain, not an explicit/system prefix')
        for command in ['dpkg-deb']+([] if args.package_dir else ['apt-get']):
            if not shutil.which(command):
                parser.error('missing '+command+'; see docs/building-wsl.md')
        target=ROOT/'work/windows-toolchain'
        packages=args.package_dir.resolve() if args.package_dir else target/'packages'
        if not args.package_dir:
            packages.mkdir(parents=True,exist_ok=True)
            subprocess.run(['apt-get','download',*PACKAGES],cwd=packages,check=True)
        selected={}
        for package in sorted(packages.glob('*.deb')):
            name=subprocess.check_output(['dpkg-deb','-f',str(package),'Package'],text=True).strip()
            if name not in PACKAGES:
                continue
            if name in selected:
                raise RuntimeError('multiple package versions in cache: '+name+'; choose a single matching set')
            selected[name]=package
        missing=set(PACKAGES)-selected.keys()
        if missing:
            raise RuntimeError('incomplete MinGW package cache: '+', '.join(sorted(missing)))
        sysroot=target/'root'
        sysroot.mkdir(parents=True,exist_ok=True)
        package_rows=[]
        for name,package in sorted(selected.items()):
            subprocess.run(['dpkg-deb','-x',str(package),str(sysroot)],check=True)
            package_rows.append(dict(package=name,file=package.name,
                version=subprocess.check_output(['dpkg-deb','-f',str(package),'Version'],text=True).strip(),
                sha256=hashlib.sha256(package.read_bytes()).hexdigest()))
        toolchain=locate(local)
    report=dict(status='ready',device_accessed=False,system_install_performed=False,
                toolchain=toolchain.validate(),packages=package_rows)
    if not args.check:
        output=ROOT/'work/windows-toolchain/toolchain.json'
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
