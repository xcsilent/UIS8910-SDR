"""Check the raw-USB PAC, source identity and actual ARM verification together."""
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


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(directory,arm_report,bw0_report=None,cp_report=None):
    manifest=json.loads((directory/'build.json').read_text(encoding='utf-8'))
    pac=ROOT/manifest['pac']
    baseline=ROOT/manifest['base_pac']
    if sha(pac)!=manifest['sha256'] or sha(baseline)!=manifest['base_sha256']:
        raise ValueError('PAC/base identity differs')
    source_root=ROOT/manifest.get('source_snapshot','')
    for relative,expected in manifest['source_sha256'].items():
        if sha(source_root/relative)!=expected:
            raise ValueError('firmware source changed since build: '+relative)
    before,after=entries(baseline.read_bytes()),entries(pac.read_bytes())
    changed=[n for n in after if after[n]['data']!=before[n]['data']]
    app_name='Air720U_V403028_CSDK_demo_debug_monitor.img'
    if set(before)!=set(after) or app_name not in changed or set(changed)-{'8915DM_cat1_CSDK.img',app_name}:
        raise ValueError('unexpected PAC entry changes')
    ap=after['8915DM_cat1_CSDK.img']['data']
    oldap=before['8915DM_cat1_CSDK.img']['data']
    permitted=set(range(4,8))|set(range(24,28))|set(range(0x3e0,0x3e4))|set(range(0x13168,0x1316c))
    differences=[i for i,(old,new) in enumerate(zip(oldap,ap)) if old!=new]
    if len(oldap)!=len(ap) or set(differences)-permitted:
        raise ValueError('AP system changed outside CRC and two entry hooks')
    header=bytearray(ap[:64])
    stored=struct.unpack_from('>I',header,4)[0]
    struct.pack_into('>I',header,4,0)
    if zlib.crc32(header)&0xffffffff!=stored or zlib.crc32(ap[64:])&0xffffffff!=struct.unpack_from('>I',ap,24)[0]:
        raise ValueError('AP uImage CRC differs')
    app_payload=after['Air720U_V403028_CSDK_demo_debug_monitor.img']['data']
    if hashlib.sha256(app_payload).hexdigest()!=manifest['appimg_sha256']:
        raise ValueError('PAC APPIMG differs from build manifest')
    app=bytearray(app_payload)
    magic,size,stored=struct.unpack_from('<3I',app)
    struct.pack_into('<I',app,8,0)
    if magic!=0x41505032 or size!=len(app) or zlib.crc32(app)&0xffffffff!=stored:
        raise ValueError('APPIMG CRC/length differs')
    arm=json.loads(arm_report.read_text(encoding='utf-8'))
    if arm['status']!='passed' or sha(ROOT/arm['elf'])!=arm['elf_sha256'] or len(arm['tests'])<24:
        raise ValueError('ARM verification missing or stale')
    elf=ROOT/arm['elf']
    from elftools.elf.elffile import ELFFile
    with elf.open('rb') as stream:
        image=ELFFile(stream)
        symbols={s.name:s['st_value'] for s in image.get_section_by_name('.symtab').iter_symbols()}
        start,end=symbols['__flash_start'],symbols['__flash_end']
        if end-start!=len(app_payload):
            raise ValueError('verified ELF/PAC APPIMG flash size differs')
        rebuilt=bytearray(end-start)
        for segment in image.iter_segments():
            if segment['p_type']!='PT_LOAD':
                continue
            address=segment['p_paddr']
            data=segment.data()
            lo,hi=max(start,address),min(end,address+len(data))
            if lo<hi:
                rebuilt[lo-start:hi-start]=data[lo-address:hi-address]
        # SDK mkappimg only patches size/CRC in the ELF's flash image.
        struct.pack_into('<II',rebuilt,4,len(rebuilt),0)
        struct.pack_into('<I',rebuilt,8,zlib.crc32(rebuilt)&0xffffffff)
        if bytes(rebuilt)!=app_payload:
            raise ValueError('PAC APPIMG is not the ARM-tested ELF load image')
    if struct.unpack_from('<I',ap,0x13168)[0]!=symbols['debug_at_write_filter'] or struct.unpack_from('<I',ap,0x3e0)[0]!=symbols['debug_data_abort_gate']:
        raise ValueError('PAC hooks do not point to verified ELF')
    if symbols['__ram_start']!=0x80f00000 or symbols['__ram_end']>0x81000000:
        raise ValueError('APPIMG RAM reservation exceeded')
    extra_dependencies={}
    is_bw0=manifest.get('data_source')=='bw0_capture'
    if is_bw0:
        if not bw0_report or not cp_report:
            raise ValueError('BW0 candidate requires AP service and CP ARM reports')
        cp_manifest_path=ROOT/manifest['cp_modules']
        cp_manifest=json.loads(cp_manifest_path.read_text(encoding='utf-8'))
        if hex(symbols['test_ram'])!=cp_manifest['ap_mailbox']:
            raise ValueError('AP/CP mailbox differs')
        for name in ('resident','control'):
            blob=(ROOT/cp_manifest[name]['path']).read_bytes()
            if hashlib.sha256(blob).hexdigest()!=cp_manifest[name]['sha256']:
                raise ValueError('CP module identity differs')
            # Match the actual ELF symbol byte span in the PAC flash image.
            address=symbols['sdr_bw0_'+name+'_blob']
            if app_payload[address-start:address-start+len(blob)]!=blob:
                raise ValueError('PAC does not embed the paired CP '+name)
        for report_path in (bw0_report,cp_report):
            tested=json.loads(report_path.read_text(encoding='utf-8'))
            if tested['status']!='passed':
                raise ValueError('BW0 ARM report did not pass')
            if report_path==bw0_report and tested['elf_sha256']!=sha(elf):
                raise ValueError('BW0 worker test used another ELF')
            if report_path==cp_report and any(tested[name+'_sha256']!=cp_manifest[name]['sha256']
                                              for name in ('resident','control')):
                raise ValueError('CP ARM test used other module binaries')
            for relative,expected in tested['dependencies'].items():
                if sha(ROOT/relative)!=expected:
                    raise ValueError('BW0 ARM evidence is stale: '+relative)
            extra_dependencies[report_path.relative_to(ROOT).as_posix()]=sha(report_path)
        baseline=ROOT/manifest['usb_baseline_evidence']
        evidence=json.loads(baseline.read_text(encoding='utf-8'))
        if (evidence.get('source')!='fixed_ap_buffer_benchmark' or
                evidence['config']['duration_ms']<60000 or not evidence.get('transport_completed') or
                evidence.get('status') not in ('passed','completed_with_loss')):
            raise ValueError('hardware USB baseline evidence differs')
        extra_dependencies[baseline.relative_to(ROOT).as_posix()]=sha(baseline)
    return dict(status='passed',hardware_tested=False,device_accessed=False,pac=manifest['pac'],
        sha256=manifest['sha256'],changed_pac_entries=changed,unchanged_cp_rf_nv_boot=True,
        ap_changes_limited_to_two_hooks_and_crc=True,pac_and_appimg_crc_verified=True,
        arm_code_tests=len(arm['tests']),arm_report=arm_report.relative_to(ROOT).as_posix(),
        source_identity_verified=True,verified_elf_matches_pac_appimg=True,app_ram_end=hex(symbols['__ram_end']),
        source_snapshot=manifest.get('source_snapshot'),
        paired_cp_modules_embedded=is_bw0,
        dependencies={**extra_dependencies,**{(source_root/relative).relative_to(ROOT).as_posix():digest for relative,digest in manifest['source_sha256'].items()},arm['elf']:arm['elf_sha256'],
            arm_report.relative_to(ROOT).as_posix():sha(arm_report),
            Path(__file__).relative_to(ROOT).as_posix():sha(Path(__file__))},
        limitation=('BW0 AP/CP packaging and simulated code verified; physical RF/DMA/USB and restart require manual flash and hardware experiment' if is_bw0 else
                    'fixed AP buffer benchmark; USB enumeration DMA and throughput require manual flash and hardware experiment'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True,help='explicit candidate directory')
    parser.add_argument('--arm-report',type=Path,required=True,help='matching AP ARM verification, not an old default')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--bw0-report',type=Path)
    parser.add_argument('--cp-report',type=Path)
    args=parser.parse_args()
    report=verify(args.directory.resolve(),args.arm_report.resolve(),
                  args.bw0_report.resolve() if args.bw0_report else None,
                  args.cp_report.resolve() if args.cp_report else None)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
