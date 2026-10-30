"""Locate and validate a Linux-hosted Windows x64 MinGW POSIX toolchain.

Shared by host builders; does not install packages or change the system PATH.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_HINT = ('Install Ubuntu packages gcc-mingw-w64-x86-64-posix '
                'g++-mingw-w64-x86-64-posix binutils-mingw-w64-x86-64, '
                'or run python3 -B tools/usb/prepare_host_toolchain.py. '
                'See docs/building-wsl.md for Linux runtime dependencies.')


class Mingw:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.bin = self.root/'bin'
        self.cc = self.bin/'x86_64-w64-mingw32-gcc-posix'
        self.cxx = self.bin/'x86_64-w64-mingw32-g++-posix'
        self.windres = self.bin/'x86_64-w64-mingw32-windres'
        self.objdump = self.bin/'x86_64-w64-mingw32-objdump'
        self.env = dict(os.environ)
        self.env['PATH'] = str(self.bin)+os.pathsep+self.env.get('PATH','')

    def query(self, compiler, *args):
        try:
            result = subprocess.run([str(compiler), *args], env=self.env,
                                    capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(str(error)+'\n'+PACKAGE_HINT) from error
        if result.returncode:
            raise RuntimeError(result.stdout+result.stderr+'\n'+PACKAGE_HINT)
        return result.stdout.strip()

    def validate(self, cpp=True):
        required = [self.cc,self.windres,self.objdump]+([self.cxx] if cpp else [])
        missing = [str(p) for p in required if not p.is_file()]
        if missing:
            raise RuntimeError('Missing MinGW tools: '+', '.join(missing)+'\n'+PACKAGE_HINT)
        if self.query(self.cc,'-dumpmachine') != 'x86_64-w64-mingw32':
            raise RuntimeError('MinGW must target Windows x64')
        versions = dict(cc=self.query(self.cc,'--version').splitlines()[0])
        if cpp:
            versions['cxx'] = self.query(self.cxx,'--version').splitlines()[0]
        return dict(root=str(self.root), target='x86_64-w64-mingw32', versions=versions)

    def runtime(self, name):
        path = Path(self.query(self.cc,'-print-file-name='+name))
        if not path.is_file():
            raise RuntimeError('MinGW runtime not found: '+name+'\n'+PACKAGE_HINT)
        return path.resolve()


def locate(root=None, cpp=True):
    if sys.platform != 'linux':
        raise RuntimeError('Run with Linux Python3 inside WSL/Ubuntu; the output targets Windows x64.')
    configured = root or os.environ.get('UIS8910_MINGW_ROOT')
    if configured:
        toolchain = Mingw(configured)
    else:
        local = ROOT/'work/windows-toolchain/root/usr'
        if (local/'bin/x86_64-w64-mingw32-gcc-posix').is_file():
            toolchain = Mingw(local)
        else:
            found = shutil.which('x86_64-w64-mingw32-gcc-posix')
            if not found:
                raise RuntimeError(PACKAGE_HINT)
            toolchain = Mingw(Path(found).parent.parent)
    toolchain.validate(cpp)
    return toolchain
