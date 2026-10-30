"""Build pinned SoapySDR0.8.1 for Windows using bundled upstream source.

WSL/Linux Python3, CMake, Ninja and POSIX MinGW C/C++ are required to compile.
--check-source verifies the small source archive on any platform without tools.
No Git checkout, network fetch or Soapy binary SDK is needed for this step.
"""
import argparse
from pathlib import Path
from pathlib import PurePosixPath
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
COMMIT = '1cf5a539a21414ff509ff7d0eedfc5fa8edb90c6'
sys.path.insert(0,str(ROOT/'tools'))
from sdr.host_toolchain import locate


def source_input(destination=None):
    manifest=json.loads((ROOT/'build-support/host-manifest.json').read_text(encoding='utf-8'))
    if manifest['commit']!=COMMIT:
        raise ValueError('Soapy source commit differs from supported ABI')
    row=manifest['source_archive']
    archive=(ROOT/row['path']).resolve()
    if not archive.is_relative_to(ROOT/'build-support') or hashlib.sha256(archive.read_bytes()).hexdigest()!=row['sha256']:
        raise ValueError('Soapy source archive identity differs')
    expected={r['path']:r for r in row['files']}
    with zipfile.ZipFile(archive) as z:
        files=[i for i in z.infolist() if not i.is_dir()]
        if len(files)!=len(expected) or {i.filename for i in files}!=set(expected):
            raise ValueError('Soapy archive file list differs')
        for info in files:
            name=PurePosixPath(info.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in info.filename or ':' in info.filename:
                raise ValueError('unsafe Soapy source member')
            data=z.read(info)
            if len(data)!=expected[info.filename]['bytes'] or hashlib.sha256(data).hexdigest()!=expected[info.filename]['sha256']:
                raise ValueError('Soapy source member identity differs: '+info.filename)
            if destination:
                target=(destination/info.filename).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise ValueError('Soapy source member escapes build area')
                if target.exists():
                    # A preserved Windows Git checkout may use CRLF. Compare
                    # normalized text, without rewriting the original tree.
                    if target.read_bytes().replace(b'\r\n',b'\n')!=data.replace(b'\r\n',b'\n'):
                        raise ValueError('independent Soapy source edits: '+info.filename)
                else:
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(data)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--area',type=Path,default=ROOT/'work/soapysdr')
    parser.add_argument('--toolchain-root',type=Path)
    parser.add_argument('--jobs',type=int,default=3)
    parser.add_argument('--check-source',action='store_true',help='verify bundled source only; portable, no extraction')
    args=parser.parse_args()
    if args.check_source:
        manifest=source_input()
        print(json.dumps(dict(status='passed',device_accessed=False,commit=manifest['commit'],source_files=len(manifest['source_archive']['files'])),indent=2))
        return
    if not 1<=args.jobs<=64:
        parser.error('--jobs must be in 1..64')
    area=args.area.resolve()
    if not area.is_relative_to(ROOT/'work') or area==ROOT/'work':
        parser.error('SDK area must be strictly inside work/')
    for name in ['cmake','ninja']:
        if not shutil.which(name):
            parser.error('missing '+name+'; install dependencies from docs/building-wsl.md')
    toolchain=locate(args.toolchain_root)
    area.mkdir(parents=True, exist_ok=True)
    source = area / 'source'
    manifest=source_input(source)
    (area / 'source.json').write_text(json.dumps(dict(repository=manifest['repository'],
        tag=manifest['tag'],commit=manifest['commit'],archive_sha256=manifest['source_archive']['sha256']),indent=2)+'\n',encoding='utf-8')
    env=toolchain.env
    subprocess.run(['cmake', '-S', str(source), '-B', str(area / 'build'), '-G', 'Ninja',
        '-DCMAKE_POLICY_VERSION_MINIMUM=3.5', '-DCMAKE_SYSTEM_NAME=Windows',
        '-DCMAKE_C_COMPILER=' + str(toolchain.cc),
        '-DCMAKE_CXX_COMPILER=' + str(toolchain.cxx),
        '-DCMAKE_RC_COMPILER=' + str(toolchain.windres),
        '-DCMAKE_INSTALL_PREFIX=' + str(area / 'install'), '-DCMAKE_BUILD_TYPE=Release',
        '-DSOAPY_SDR_EXTVER=g'+COMMIT[:8],
        '-DENABLE_PYTHON=OFF', '-DENABLE_PYTHON3=OFF', '-DENABLE_PYTHON2=OFF',
        '-DCMAKE_SHARED_LINKER_FLAGS=-static-libgcc -static-libstdc++',
        '-DCMAKE_EXE_LINKER_FLAGS=-static-libgcc -static-libstdc++'], env=env, check=True)
    subprocess.run(['cmake', '--build', str(area / 'build'), '-j', str(args.jobs)], env=env, check=True)
    subprocess.run(['cmake', '--install', str(area / 'build')], env=env, check=True)


if __name__ == '__main__':
    main()
