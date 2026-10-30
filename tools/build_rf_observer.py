"""Build a cold-load RF command-entry observer in proven RFv6 padding.

No PAC, hardware access, live patch, initialization replay or RFFE reads.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/verify'))
from rf_image import current_pac_image

ENTRY=0x10e8
SKIP=0x60f6
STUB=0x60fa
COUNTER=0x6118
LAST_POINTER=0x611c
END=0x6122


def jal(pc,target):
    displacement=target-pc
    assert displacement%2==0 and -(1<<20)<=displacement<(1<<20)
    value=displacement&0x1fffff
    return struct.pack('<I',((value>>20)<<31)|(((value>>1)&1023)<<21)|
                       (((value>>11)&1)<<20)|(((value>>12)&255)<<12)|0x6f)


def build_code(original):
    # Only a4/a5 are used; both are overwritten by the unchanged original
    # helper. Its first LBU executes in the stub before returning to 0x10ec.
    assert original[ENTRY:ENTRY+4]==bytes.fromhex('83470500')
    assert original[SKIP:END]==b'\x01\x00'*((END-SKIP)//2)
    code=bytearray()
    def half(value):code.extend(struct.pack('<H',value))
    half(0x6001|(14<<7)|(6<<2))  # c.lui a4,6
    code.extend(struct.pack('<I',(0x118<<20)|(14<<15)|(14<<7)|0x13))
    half(0x4000|((14-8)<<7)|((15-8)<<2))  # c.lw a5,0(a4)
    half(0x0001|(15<<7)|(1<<2))  # c.addi a5,1
    half(0xc000|((14-8)<<7)|((15-8)<<2))  # c.sw a5,0(a4)
    half(0xc000|((14-8)<<7)|(1<<6)|((10-8)<<2))  # c.sw a0,4(a4)
    code.extend(original[ENTRY:ENTRY+4])
    code.extend(jal(STUB+len(code),ENTRY+4))
    assert STUB+len(code)<=COUNTER
    patched=bytearray(original)
    patched[ENTRY:ENTRY+4]=jal(ENTRY,STUB)
    # RXON normally falls through this padding. Skip the entire observer and
    # its data; keep 0x6122 at its original address for AUIPC correctness.
    patched[SKIP:SKIP+4]=jal(SKIP,END)
    patched[STUB:STUB+len(code)]=code
    patched[COUNTER:LAST_POINTER+4]=bytes(8)
    spans=[(ENTRY,ENTRY+4),(SKIP,END)]
    assert len(patched)==len(original)
    assert all(a==b or any(lo<=i<hi for lo,hi in spans)
               for i,(a,b) in enumerate(zip(original,patched)))
    return bytes(patched),len(code)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    output=args.output_dir.resolve()
    assert output.is_relative_to(ROOT) and not output.exists(),'choose a new project build directory'
    image,dependencies=current_pac_image()
    # Ownership comes from this one historical reconstruction, not a guessed
    # zero-filled BSS area. The archive is data only and is never executed.
    ownership=ROOT/'archive/legacy-2026-10-23/records/experiments/rf-rxon-request-v3/build.json'
    lineage=ROOT/'archive/legacy-2026-10-23/records/experiments/rf-rxon-finish-native/build.json'
    retained=ROOT/'archive/consolidation-2026-10-28/outputs/firmware/current/riscV.bin'
    request=json.loads(ownership.read_text())['unit']
    original=image.read_bytes(); digest=hashlib.sha256(original).hexdigest()
    assert digest==json.loads(lineage.read_text())['patched_image_sha256']
    assert original==retained.read_bytes()
    assert int(request['start'],0)+request['active_bytes']==SKIP
    assert int(request['end'],0)==END
    patched,code_bytes=build_code(original)
    output.mkdir(parents=True)
    target=output/'riscV.bin';target.write_bytes(patched)
    dependencies+=[Path(__file__),ownership,lineage,retained,image]
    report=dict(status='built_offline_observer_requires_native_verification',
        device_accessed=False,pac_generated=False,flashed=False,
        parent_image_sha256=digest,image=target.relative_to(ROOT).as_posix(),
        image_sha256=hashlib.sha256(patched).hexdigest(),
        command_helper=hex(ENTRY),stub=hex(STUB),stub_bytes=code_bytes,
        counter_address=hex(COUNTER),last_pointer_address=hex(LAST_POINTER),
        request_padding_skip=dict(start=hex(SKIP),end=hex(END)),
        semantics='Modulo2^32 helper entry count and last NV command pointer; updated before controller writes, not command completion, ACK or RF reception. Cold-load only; no live RF cache assumptions.',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies})
    path=output/'build.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],build=path.relative_to(ROOT).as_posix(),image_sha256=report['image_sha256'])))


if __name__=='__main__':main()
