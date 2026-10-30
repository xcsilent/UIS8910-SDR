"""Verify and unpack the pinned, local Windows firmware build dependencies.

No network, system installation, SDK checkout modification or hardware access.
The small archives travel with the source review package; the original full
SDK and the other local toolchains are left in place.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import os
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(check_only=False):
    manifest = json.loads((ROOT/'build-support/manifest.json').read_text(encoding='utf-8'))
    result = {}
    for bundle in manifest['bundles']:
        archive = (ROOT/bundle['path']).resolve()
        if not archive.is_relative_to(ROOT/'build-support') or sha(archive) != bundle['sha256']:
            raise ValueError('build archive identity differs: '+bundle['path'])
        destination = (ROOT/'work/build-deps'/bundle['destination']).resolve()
        if not destination.is_relative_to(ROOT/'work/build-deps'):
            raise ValueError('dependency destination escapes build cache')
        expected = {row['path']: row for row in bundle['files']}
        with zipfile.ZipFile(archive) as source:
            names = source.namelist()
            if len(names) != len(expected) or set(names) != set(expected):
                raise ValueError('unexpected dependency archive members')
            for name in names:
                relative = PurePosixPath(name)
                if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
                    raise ValueError('unsafe archive member: '+name)
                info = source.getinfo(name)
                row = expected[name]
                if info.file_size != row['bytes']:
                    raise ValueError('dependency member length differs: '+name)
                data = source.read(name)
                if hashlib.sha256(data).hexdigest() != row['sha256']:
                    raise ValueError('dependency member identity differs: '+name)
                if check_only:
                    continue
                target = (destination/name).resolve()
                if not target.is_relative_to(destination):
                    raise ValueError('dependency member escapes cache: '+name)
                if target.exists():
                    if sha(target) != row['sha256']:
                        raise ValueError('modified dependency cache; use a fresh work/build-deps: '+str(target))
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
        result[bundle['destination']] = destination
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='verify bundled bytes without extracting')
    args = parser.parse_args()
    if os.name != 'nt' and not args.check:
        parser.error('bundled firmware compiler targets Windows; use --check for portable archive validation')
    paths = prepare(args.check)
    print(json.dumps(dict(status='passed', device_accessed=False,
                         extracted=not args.check, paths={k:str(v) for k,v in paths.items()}), indent=2))


if __name__ == '__main__':
    main()
