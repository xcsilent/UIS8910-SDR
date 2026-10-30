"""Check a proposed one-byte FEM experiment in native RF code, offline only."""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from verify_rffe_init_native import RffeNative, run_slice, X
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_SP, UC_ARM_REG_PC

ROOT = Path(__file__).resolve().parents[2]


def copy_frontend(blob, nv, cpu=None):
    """Execute actual CP caller, veneer and scatter-loaded memcpy, not a model."""
    base = 0x801ab000
    scatter = struct.unpack_from('<4I', blob, 0x2bc4dc)
    assert scatter == (0x8025b8e8, 0x804750bc, 0x804000, 0x29724)
    assert struct.unpack_from('<I', blob, 0x802e9158-base)[0] == 0x804388
    if cpu is None:
        cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        cpu.mem_map(0x801b9000,0x1000)
        cpu.mem_write(0x801b9aba,blob[0xeaba:0xeacc])
        cpu.mem_map(0x802e9000,0x1000)
        cpu.mem_write(0x802e9154,blob[0x802e9154-base:0x802e915c-base])
        _, source, destination, length = scatter
        cpu.mem_map(destination,0x30000)
        cpu.mem_write(destination,blob[source-base:source-base+length])
        cpu.mem_map(0x200000,0x20000)
        cpu.mem_map(0x50009000,0x3000)
    cpu.mem_write(0x200008,struct.pack('<I',0x210000))
    cpu.mem_write(0x210000,nv)
    cpu.reg_write(UC_ARM_REG_R4,0x500096b0)
    cpu.reg_write(UC_ARM_REG_R5,0x200000)
    cpu.reg_write(UC_ARM_REG_SP,0x21f000)
    writes = []
    hook = cpu.hook_add(UC_HOOK_MEM_WRITE,lambda c,a,p,n,v,x:writes.append((p,n)))
    cpu.emu_start(0x801b9aba|1,0x801b9acc,count=10000)
    cpu.hook_del(hook)
    assert cpu.reg_read(UC_ARM_REG_PC)==0x801b9acc
    assert all((0x5000974c<=p and p+n<=0x5000a8c8) or
               (0x21e000<=p and p+n<=0x21f000) for p,n in writes), writes
    copied = bytes(cpu.mem_read(0x5000974c,0x117c))
    assert copied==nv[0x2ac:0x1428]
    return copied, cpu


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--nv', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists() and args.output.resolve().is_relative_to(ROOT)
    current = ROOT / 'outputs/firmware/current/manifest.json'
    installed = json.loads(current.read_text(encoding='utf-8'))['installed_firmware']
    build_path = ROOT / installed['build_evidence']
    build = json.loads(build_path.read_text(encoding='utf-8'))
    image = args.image.read_bytes()
    assert hashlib.sha256(image).hexdigest() == build['rf_image_sha256']
    cp = ROOT / 'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin/cp.bin'
    blob = cp.read_bytes()
    assert hashlib.sha256(blob).hexdigest()==installed['cp_baseline_sha256']
    raw = args.nv.read_bytes()
    assert len(raw) == 16384
    assert struct.unpack_from('<H', raw, 0x28)[0] == 5
    assert struct.unpack_from('<H', raw, 0x2c)[0] == 8
    # Only use the two known commands in this board snapshot, not arbitrary USIDs.
    first = 0x310 + 4 * 16
    second = 0x310 + 6 * 16
    assert raw[first:first+4] == bytes((5, 0, 13, 0))
    assert raw[second:second+4] == bytes((2, 0, 13, 0))
    baseline_copy, _ = copy_frontend(blob,raw)
    header = ROOT / 'inputs/reference-source/riscv-pulp-legacy/riscv-opc.h'
    pin = header.parent / 'source-manifest.json'
    assert hashlib.sha256(header.read_bytes()).hexdigest() == next(
        r['sha256'] for r in json.loads(pin.read_text())['files'] if r['file'] == header.name)
    defs = {k: int(v, 16) for k, v in re.findall(
        r'#define\s+((?:MATCH|MASK)_\w+)\s+(0x[0-9a-fA-F]+)', header.read_text())}
    rules = [(n, defs['MATCH_'+n], defs['MASK_'+m]) for n,m in
             [('EXTHZ','PALUS'), ('BCLR','PALU2'), ('BNEM1','BNEM1')]]
    results = []
    for row, selector, offset in ((4,4,first),(6,6,second)):
        variants = []
        for value in (5,2):
            nv = bytearray(raw)
            nv[offset] = value
            assert [i for i,(a,b) in enumerate(zip(raw,nv)) if a!=b] == (
                [] if value==raw[offset] else [offset])
            copied, copy_cpu = copy_frontend(blob,bytes(nv))
            assert [i for i,(a,b) in enumerate(zip(baseline_copy,copied)) if a!=b] == (
                [] if value==raw[offset] else [offset-0x2ac])
            # Native open and close dispatch; all non-observer RAM writes checked.
            operations = []
            for op in (0,1):
                n = RffeNative(image, rules)
                n.cpu.mem_write(0x974c,copied)
                n.cpu.mem_write(0x940c+selector*2,struct.pack('<H',row))
                n.cpu.mem_write(0xaf74,struct.pack('<H',1))
                n.cpu.reg_write(X[10],0x8000|(selector<<4)|op)
                unexpected = []
                def observe(cpu,access,address,size,written,context):
                    if address<0x10000 and address not in (0x6118,0x611c):
                        unexpected.append((address,size,written))
                n.cpu.hook_add(UC_HOOK_MEM_WRITE,observe)
                run_slice(n,0x7140,0xf000,defs)
                assert not unexpected, unexpected
                expected = [(0x3c008,value if op==0 else 0,2),
                            (0x3c000,0,2),(0x3c004,(13<<10)|0x72,2)]
                assert n.writes == expected, n.writes
                operations.append(n.writes)
            # Re-run original copier on baseline: RF-copy restoration is exact
            # in this emulator. This is not a live update/cache protocol proof.
            restored, _ = copy_frontend(blob,raw,copy_cpu)
            assert restored==baseline_copy
            variants.append(dict(value=value,open_writes=operations[0],close_writes=operations[1],
                nv_byte_offset=hex(offset),rf_local_byte=hex(0x974c+offset-0x2ac),
                original_cp_copy_executed=True,baseline_copy_restore_matches=True))
        assert variants[0]['close_writes']==variants[1]['close_writes']
        results.append(dict(row=row,selector=selector,variants=variants))
    deps = [Path(__file__),args.image,args.nv,current,build_path,header,pin,cp,
            ROOT/'tools/verify/verify_rffe_init_native.py',
            ROOT/'tools/verify/verify_rf_frequency_native.py',ROOT/'tools/verify/verify_rf_mode_native.py']
    result = dict(status='passed',device_accessed=False,hardware_tested=False,
        image_sha256=hashlib.sha256(image).hexdigest(),cases=results,
        original_cp_copy=dict(entry='0x801b9aba',stop='0x801b9acc',source_offset='0x2ac',
            destination='0x5000974c',bytes=0x117c,scatter_loaded_memcpy='0x804388'),
        scope='Actual CP copy slice and RF dispatch under synthetic memory. One-byte NV substitution changes only open controller data, with identical close writes and no other retained RF RAM writes. Does not prove call lifetime, live update/cache protocol, ACK, physical routing or reception.',
        dependencies={p.resolve().relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in deps})
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status='passed',anchor_rows=2,variants=4,dispatch_cases=8,device_accessed=False)))


if __name__ == '__main__':
    main()
