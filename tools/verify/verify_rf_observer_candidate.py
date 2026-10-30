"""Check final RF observer PAC composition, layout and container rejection paths."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/usb'))
from pac import entries
from modem_container import files,replace_file


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--layout-report',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    build_path=args.directory.resolve()/'build.json';build=json.loads(build_path.read_text())
    dependencies=[Path(__file__),build_path,args.layout_report.resolve()]
    for report in (build,json.loads(args.layout_report.read_text())):
        assert report['status'] in ('passed','built_verified_candidate_for_manual_flash')
        for name,digest in report['dependencies'].items():
            path=ROOT/name;assert sha(path)==digest,name;dependencies.append(path)
    pac=ROOT/build['pac'];assert sha(pac)==build['sha256']
    ap=json.loads((ROOT/build['ap_build']).read_text())
    installed=ROOT/ap['base_pac'];before=entries(installed.read_bytes());after=entries(pac.read_bytes())
    modem=next(n for n in after if 'BB_RF_SS_NoVolte_cus.img' in n)
    changed=[name for name in after if after[name]['data']!=before[name]['data']]
    assert set(changed)=={modem,'Air720U_V403028_CSDK_demo_debug_monitor.img'}
    original_files=files(before[modem]['data']);final_files=files(after[modem]['data'])
    assert set(original_files)==set(final_files)
    assert [name for name in final_files if final_files[name]['data']!=original_files[name]['data']]==['riscV.bin.000']
    # Real container rejection checks: never allow corrupted pages, duplicate
    # page ownership, truncated images or writes exceeding reserved capacity.
    source=before[modem]['data'];record=original_files['riscV.bin.000'];rejected=[]
    mutations=[]
    corrupt=bytearray(source);corrupt[record['pages'][0]*512+4]^=1
    mutations.append(('corrupted payload CRC',bytes(corrupt)))
    corrupt=bytearray(source);node=record['node']*512
    struct.pack_into('<H',corrupt,node+102,record['pages'][0])
    struct.pack_into('<I',corrupt,node+508,zlib.crc32(corrupt[node:node+508]))
    mutations.append(('duplicate page list with valid node CRC',bytes(corrupt)))
    mutations.append(('truncated image',source[:-1]))
    for name,data in mutations:
        try:files(data)
        except AssertionError:rejected.append(name)
        else:raise AssertionError('invalid modem container accepted: '+name)
    try:replace_file(source,'riscV.bin.000',bytes(len(record['pages'])*500+1))
    except AssertionError:rejected.append('replacement exceeds allocated pages')
    else:raise AssertionError('oversize replacement accepted')
    dependencies+=[pac,installed,ROOT/'tools/usb/modem_container.py',ROOT/'tools/usb/pac.py']
    report=dict(status='passed',device_accessed=False,hardware_tested=False,
        pac=build['pac'],sha256=build['sha256'],generation=build['generation'],
        changed_from_deployed_baseline=changed,only_rf_file_changed_in_modem=True,
        layout_report=args.layout_report.resolve().relative_to(ROOT).as_posix(),
        malformed_container_rejections=rejected,
        scope='Final candidate hash/composition and independently retained AP/CP/layout/native/decode evidence; no hardware or flashing.',
        dependencies={path.relative_to(ROOT).as_posix():sha(path) for path in dependencies})
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status='passed',sha256=build['sha256'],changed_entries=changed,rejections=rejected)))


if __name__=='__main__':main()
