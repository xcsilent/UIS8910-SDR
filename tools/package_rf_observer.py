"""Combine a verified AP/CP service candidate with a verified RF observer.

Uses only existing modem page allocation; never deploys or changes current.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/usb'))
from pac import entries,replace
from modem_container import files,replace_file


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(path):
    report=json.loads(path.read_text())
    assert report['status']=='passed',path
    for name,digest in report.get('dependencies',{}).items():assert sha(ROOT/name)==digest,name
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ap-directory',type=Path,required=True)
    parser.add_argument('--ap-verification',type=Path,required=True)
    parser.add_argument('--rf-build',type=Path,required=True)
    parser.add_argument('--rf-verification',type=Path,required=True)
    parser.add_argument('--trace-verification',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();output=args.output_dir.resolve()
    assert output.is_relative_to(ROOT/'outputs/firmware') and not output.exists()
    ap_report=validate(args.ap_verification.resolve());rf_report=validate(args.rf_verification.resolve())
    trace=validate(args.trace_verification.resolve());assert trace['trace_abi']==5
    ap_path=args.ap_directory.resolve()/'build.json';ap=json.loads(ap_path.read_text())
    rf_path=args.rf_build.resolve();rf=json.loads(rf_path.read_text())
    for name,digest in rf['dependencies'].items():assert sha(ROOT/name)==digest,name
    image=ROOT/rf['image'];assert sha(image)==rf['image_sha256']==rf_report['image_sha256']
    assert rf_report['observer_verification']['rxon_fallthrough_skips_code_and_data']
    base=ROOT/ap['pac'];assert sha(base)==ap['sha256']==ap_report['sha256']
    cp_path=ROOT/ap['cp_modules'];cp=json.loads(cp_path.read_text())
    assert cp['rf_status_trace']['abi']==5 and trace['dependencies'][cp_path.relative_to(ROOT).as_posix()]==sha(cp_path)
    before=entries(base.read_bytes());name=next(n for n in before if 'BB_RF_SS_NoVolte_cus.img' in n)
    modem=before[name]['data'];old=files(modem)['riscV.bin.000']['data']
    codec=ROOT/'inputs/repositories/rda8910-csdk-hotelec/tools/win32/lzmar.exe'
    with tempfile.TemporaryDirectory(dir=ROOT/'work') as temporary:
        directory=Path(temporary);compressed=directory/'encoded';decoded=directory/'decoded';original=directory/'original'
        def run(*args):
            result=subprocess.run([str(codec),*map(str,args)],capture_output=True,timeout=10)
            assert result.returncode==0,repr(result.stdout+result.stderr)
        original.write_bytes(old);run('d2',original,decoded)
        assert sha(decoded)==rf['parent_image_sha256']
        run('e2',65536,image,compressed)
        changed=replace_file(modem,'riscV.bin.000',compressed.read_bytes())
        final=replace(base.read_bytes(),{name:changed})
        reread=entries(final)
        compressed.write_bytes(files(reread[name]['data'])['riscV.bin.000']['data'])
        run('d2',compressed,decoded);assert decoded.read_bytes()==image.read_bytes()
    assert all(row['data']==reread[key]['data'] for key,row in before.items() if key!=name)
    output.mkdir(parents=True)
    target=output/'Air724U_UIS8910_SDR_RF_Observer_v28.pac';target.write_bytes(final)
    shutil.copy2(image,output/'riscV.bin')
    dependencies=[Path(__file__),ROOT/'tools/usb/modem_container.py',ROOT/'tools/usb/pac.py',
        ap_path,rf_path,image,base,cp_path,codec,args.ap_verification.resolve(),args.rf_verification.resolve(),args.trace_verification.resolve()]
    snapshot=output/'source-snapshot'
    for path in dependencies:
        dest=snapshot/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
    report=dict(status='built_verified_candidate_for_manual_flash',flashed=False,hardware_tested=False,device_accessed=False,
        pac=target.relative_to(ROOT).as_posix(),sha256=sha(target),bytes=len(final),
        base_pac=base.relative_to(ROOT).as_posix(),base_sha256=sha(base),
        ap_build=ap_path.relative_to(ROOT).as_posix(),cp_modules=cp_path.relative_to(ROOT).as_posix(),
        generation=cp['generation'],rf_status_trace_abi=5,
        ap_test_ram=ap['ap_test_ram'],app_ram_end=ap['app_ram_end'],
        rf_image_sha256=rf['image_sha256'],rf_parent_sha256=rf['parent_image_sha256'],
        changed_entries=[name],other_modem_files_unchanged=True,other_pac_entries_unchanged=True,
        rf_decompression_readback_verified=True,pac_and_page_crc_verified=True,
        observer_semantics=rf['semantics'],
        scope='Verified AP/CP candidate plus cold-load RF observer. No hardware/cache/timing/ACK/reception proof. Current v27 remains installed until user flash and runtime verification.',
        dependencies={p.relative_to(ROOT).as_posix():sha(p) for p in dependencies})
    (output/'build.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
