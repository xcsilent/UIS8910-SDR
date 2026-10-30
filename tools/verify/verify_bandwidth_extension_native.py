"""Bounded native post-BW5 mode behavior; no hardware or firmware changes."""
import hashlib
import json
from pathlib import Path
import re
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/verify'))
from verify_rf_mode_native import run


def main():
    header = ROOT/'inputs/reference-source/riscv-pulp-legacy/riscv-opc.h'
    manifest = header.with_name('source-manifest.json')
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    pinned = json.loads(manifest.read_text())
    assert sha(header) == next(r['sha256'] for r in pinned['files'] if r['file'] == header.name)
    defs = {k:int(v,16) for k,v in re.findall(r'#define\s+((?:MATCH|MASK)_\w+)\s+(0x[0-9a-fA-F]+)',header.read_text())}
    pairs = [('EXTHZ','PALUS'),('BCLR','PALU2'),('BNEM1','BNEM1'),('BEQM1','BEQM1'),('LHUPOST','LPOST'),('SHPOST','SPOST'),('LWRR','LRR')]
    rules = [(name,defs['MATCH_'+name],defs['MASK_'+mask]) for name,mask in pairs]
    source = ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin/riscV.bin'
    image = source.read_bytes()
    cases = []
    tail = [0x32038,0x3203c,0x32040,0x32044,0x32048,0x3204c,0x32050,0x32070,0x32084]
    for mode in (0,1,2,3,4,5,6,7,8,15,65535):
        for flag in (0,1):
            for initial in (0,65535):
                result = run(image,rules,mode,flag,initial)
                writes = result['writes']
                if mode <= 5:
                    assert len(writes) == 45
                    assert [int(w['address'],16) for w in writes[:2]] == [0x32000,0x32004]
                else:
                    assert [int(w['address'],16) for w in writes] == tail
                    assert all(w['bytes'] == 2 and w['value'] == 0 for w in writes)
                cases.append(result)
    report = dict(status='passed',recorded_at=datetime.now().astimezone().isoformat(),
        device_accessed=False,hardware_tested=False,native_entry='0x3a7c',cases=cases,
        conclusion='Native mode6/7 and sampled higher values only clear nine common tail registers; they do not program the mode controls or filter coefficients. Removing host/firmware range guards would not create a new bandwidth profile.',
        scope='Actual RF BIN instructions with pinned legacy instruction modeling and synthetic MMIO; not analog/filter or chip physical limit evidence.',
        next_action='Trace independent mode control/decimation and coefficient programming, then define explicit experimental profiles. Do not assign rates to unused BW enum values.',
        dependencies={p.relative_to(ROOT).as_posix():sha(p) for p in (Path(__file__),ROOT/'tools/verify/verify_rf_mode_native.py',header,manifest,source)})
    output = ROOT/'records/usb/bandwidth-native-mode-verification.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(status='passed',cases=len(cases),modes_0_to_5_writes=45,post_BW5_sampled_modes_writes=9)))


if __name__ == '__main__':main()
