"""Compare native and reconstructed RF arithmetic at sub-824 MHz candidates.

This is an offline arithmetic check, not an RF range or PLL-lock test.
"""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/verify'))
from verify_rf_frequency_native import Native, Replica, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--working-raw', type=int, nargs='+', default=[7000000,7290000,7500000,7800000,8000000,8100000,8240000])
    parser.add_argument('--output', type=Path, default=ROOT / 'records/rf/lowband-native-sub824.json')
    args = parser.parse_args()
    if any(v <= 0 or v >= 10000000 for v in args.working_raw):
        parser.error('working raw values must be positive and below the 1 GHz arithmetic branch')
    source = ROOT / 'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin/riscV.bin'
    header = ROOT / 'inputs/reference-source/riscv-pulp-legacy/riscv-opc.h'
    manifest = header.with_name('source-manifest.json')
    assert sha(header) == next(x['sha256'] for x in json.loads(manifest.read_text())['files'] if x['file'] == header.name)
    definitions = {k: int(v, 16) for k, v in re.findall(r'#define\s+((?:MATCH|MASK)_\w+)\s+(0x[0-9a-fA-F]+)', header.read_text())}
    rules = [(n, definitions['MATCH_' + n], definitions['MASK_' + m]) for n, m in [('EXTHZ', 'PALUS'), ('BCLR', 'PALU2'), ('BNEM1', 'BNEM1')]]
    cdir = ROOT / 'firmware/rf_rebuild'
    files = [cdir / name for name in ('rf_core_frequency.c', 'rf_core_tune_flow.c', 'rf_core_tune_plan.c')]
    gcc = ROOT / 'inputs/repositories/rda8910-csdk-hotelec/prebuilts/win32/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
    build = ROOT / 'work/rf-lowband-native'
    build.mkdir(parents=True, exist_ok=True)
    elf = build / 'replica.elf'
    subprocess.run([str(gcc), '-mcpu=cortex-a5', '-mthumb', '-mfloat-abi=soft', '-Os', '-ffreestanding', '-fno-builtin', '-nostdlib', '-Wl,--build-id=none', '-Wl,-Ttext=0x100000', '-Wl,-e,rf_core_frequency_coefficients', *map(str, files), '-lgcc', '-o', str(elf)], check=True)
    image = source.read_bytes()
    replica = Replica(elf)
    cases = []
    for requested in args.working_raw:
        for selector in (4, 6):
            for state, factor in ((0, 8), (1, 7), (1, 8)):
                native = Native(image, rules)
                actual = native.coefficients(requested, selector, state, factor)
                error, data = replica.call('rf_core_frequency_coefficients', struct.pack('<IHH', requested, state, factor), 8)
                assert error == 0 and struct.unpack('<4H', data) == actual
                cases.append(dict(working_raw=requested, selector=selector, factor_state=state, table_factor=factor,
                                  effective_raw=requested * 2, q8=actual[0], fraction=(actual[1] << 16) | actual[2], selected_factor=actual[3]))
    inputs = [Path(__file__), ROOT / 'tools/verify/verify_rf_frequency_native.py', ROOT / 'tools/verify/verify_rf_mode_native.py', source, header, manifest, elf, *files]
    report = dict(status='passed', recorded_at=datetime.now().astimezone().isoformat(), device_accessed=False,
                  scope='Native RF coefficient helper and compiled reconstruction; synthetic working frequencies, selectors and factor contexts. No RF, lock, calibration or analog support claim.',
                  cases=cases, dependencies={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs})
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'records') or not output.parent.is_dir():
        raise ValueError('output must be in an existing records directory')
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status='passed', cases=len(cases), output=str(output.relative_to(ROOT)))))


if __name__ == '__main__':
    main()
