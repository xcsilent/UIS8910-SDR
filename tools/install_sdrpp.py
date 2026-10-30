"""Install the tested native module into an explicitly selected SDR++ directory.

Default is a read-only plan. --apply copies only this plugin/runtime, backs up
the existing config, and adds its module instance. Does not start SDR++/RF.
"""
from pathlib import Path
import argparse
from datetime import datetime
import hashlib
import json
import shutil

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdrpp-root',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--build-dir',type=Path,default=ROOT/'outputs/host/sdrpp')
    args=parser.parse_args()
    target=args.sdrpp_root.resolve();out=args.build_dir.resolve()
    if not out.is_relative_to(ROOT/'outputs/host'):
        parser.error('build directory must be inside outputs/host')
    build=json.loads((out/'build.json').read_text(encoding='utf-8'))
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    if sha(target/'sdrpp_core.dll')!=build['target_sdrpp_core_sha256']:
        raise RuntimeError('SDR++ core differs from the tested target; rebuild for this version first')
    for item in build['artifacts']:
        if sha(ROOT/item['path'])!=item['sha256']:raise RuntimeError('Build artifact changed: '+item['path'])
    config_path=target/'config.json';cfg=json.loads(config_path.read_text(encoding='utf-8'))
    operations=[(out/'uis8910_source.dll',target/'modules/uis8910_source.dll'),(out/'sdr_usb.dll',target/'sdr_usb.dll')]
    report=dict(status='plan',target=str(target),hardware_accessed=False,
        files=[dict(source=str(a),destination=str(b),sha256=sha(a)) for a,b in operations],
        config_change='Add enabled UIS8910 Source module instance; preserve selected source/frequency and all other settings')
    if args.apply:
        stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup=config_path.with_name('config.before-uis8910-'+stamp+'.json')
        shutil.copy2(config_path,backup)
        for source,destination in operations:
            if destination.exists():shutil.copy2(destination,destination.with_name(destination.name+'.before-'+stamp))
            shutil.copy2(source,destination)
        cfg.setdefault('moduleInstances',{})['UIS8910 Source']=dict(enabled=True,module='uis8910_source')
        temporary=config_path.with_name('config.uis8910-install.tmp')
        temporary.write_text(json.dumps(cfg,indent=4)+'\n',encoding='utf-8');temporary.replace(config_path)
        report.update(status='installed',config_backup=str(backup),
            verified_files=all(sha(a)==sha(b) for a,b in operations))
        (out/'installation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
