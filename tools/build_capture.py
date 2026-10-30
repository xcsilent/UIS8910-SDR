"""Rebuild the last verified B5 RAM capture binaries; never load or run them.

Uses a small, explicit recipe and retained sources, with no old experiment
runner, hidden work directory or historical audit chain as a prerequisite.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'work/capture-build')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if not output.is_relative_to(ROOT/'work') or output.exists():
        parser.error('choose a new output directory inside work')
    recipe = json.loads((ROOT/'firmware/capture/build-recipe.json').read_text(encoding='utf-8'))
    output.mkdir(parents=True)
    for tokens in recipe['commands']:
        command = []
        for item in tokens:
            if isinstance(item,str):
                command.append(item)
                continue
            relative = item['path']
            if relative.startswith('work/capture-build/'):
                path = output/Path(relative).name
            else:
                path = ROOT/relative
            if not command and os.name!='nt':
                command.append(path.name.removesuffix('.exe'))
            else:
                command.append(item['prefix']+str(path))
        subprocess.run(command,cwd=ROOT,check=True)
    artifacts = []
    for kind in ('resident','control'):
        path = output/(kind+'.bin')
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != recipe['expected_'+kind+'_sha256']:
            raise ValueError(kind+' differs from the verified B5 binary')
        artifacts.append(dict(path=path.relative_to(ROOT).as_posix(),bytes=path.stat().st_size,sha256=actual))
    result = dict(status='passed',profile=recipe['profile'],device_accessed=False,
                  matches_last_verified_b5_binaries=True,artifacts=artifacts)
    (output/'build.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
