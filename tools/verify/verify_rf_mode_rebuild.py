"""Compare compiled RF mode reconstruction to original RF instructions.

No device access. Legacy PULP operations use the existing bounded interpreter;
all six modes compare exact halfword write address/value/order on synthetic MMIO.
"""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/verify'))
from verify_rf_mode_native import run
from verify_rf_frequency_native import Replica


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'work/rf-mode-rebuild.json')
    args = parser.parse_args()
    sdk = ROOT / 'inputs/repositories/rda8910-csdk-hotelec'
    image_path = sdk / 'core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin/riscV.bin'
    header = ROOT / 'inputs/reference-source/riscv-pulp-legacy/riscv-opc.h'
    manifest = header.with_name('source-manifest.json')
    assert sha(header) == next(row['sha256'] for row in json.loads(manifest.read_text())['files'] if row['file'] == header.name)
    definitions = {name: int(value, 16) for name, value in re.findall(
        r'#define\s+((?:MATCH|MASK)_\w+)\s+(0x[0-9a-fA-F]+)', header.read_text())}
    rules = [(name, definitions['MATCH_' + name], definitions['MASK_' + mask])
             for name, mask in [('EXTHZ', 'PALUS'), ('BCLR', 'PALU2'),
                ('BNEM1', 'BNEM1'), ('BEQM1', 'BEQM1'), ('LHUPOST', 'LPOST'),
                ('SHPOST', 'SPOST'), ('LWRR', 'LRR')]]
    image = image_path.read_bytes()
    cases = []
    for mode in range(6):
        for flag in (0, 1, 2, 65535):
            for initial in (0, 1, 0x100, 0x3fa, 0x400, 0xa55a, 0x5aa5, 65535):
                native = run(image, rules, mode, flag, initial)
                writes = [(int(row['address'], 16), row['bytes'], row['value']) for row in native['writes']]
                assert len(writes) == 45
                cases.append((mode, flag, initial, 0, 0, writes))
    for mode in range(6):
        for index in range(4):
            for selector in (5,15,17):
                native=run(image,rules,mode,1,0xa55a,index,selector)
                writes=[(int(row['address'],16),row['bytes'],row['value']) for row in native['writes']]
                cases.append((mode,1,0xa55a,index,selector,writes))
    build = ROOT / 'work/rf-mode-rebuild'
    build.mkdir(exist_ok=True)
    gcc = sdk / 'prebuilts/win32/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
    sources = [ROOT / 'firmware/rf_rebuild/rf_core_mode.c', ROOT / 'tools/verify/rf_mode_harness.c']
    reports, binaries = [], []
    for optimization in ('-O0', '-O2'):
        binary = build / (optimization[1:] + '.elf')
        subprocess.run([str(gcc), '-mcpu=cortex-a5', '-mthumb', '-mfloat-abi=soft',
            optimization, '-ffreestanding', '-fno-builtin', '-nostdlib',
            '-Wl,--build-id=none', '-Wl,-Ttext=0x100000', '-Wl,-e,verify_mode',
            *map(str, sources), '-lgcc', '-o', str(binary)], check=True)
        binaries.append(binary)
        replica = Replica(binary)

        def call(mode, flag=1, initial=0xa55a, fail_at=0,index=0,selector=0):
            error, output = replica.call('verify_mode', struct.pack('<6I', mode, flag, initial, fail_at,index,selector), 780)
            result, calls, count = struct.unpack_from('<iII', output)
            assert error == result & 0xffffffff
            assert count <= 64
            trace = list(struct.iter_unpack('<3I', output[12:12 + count * 12]))
            return result, calls, trace

        for mode, flag, initial, index,selector,expected in cases:
            result, calls, trace = call(mode, flag, initial,index=index,selector=selector)
            actual=[(a,2,v) for op,a,v in trace if op==1]
            assert result == 0 and actual == expected, (optimization, mode, flag, initial)
            assert calls == (49 if flag == 1 else 47)+(2 if mode==0 else 1 if mode in (4,5) else 0)
        invalid = 0
        for mode in (6, 7, 0xffffffff):
            result, calls, trace = call(mode)
            assert result == -1 and calls == 0 and not trace
            invalid += 1
        failures = 0
        for mode in range(6):
            for flag in (0, 1):
                _, successful_calls, full_trace = call(mode, flag)
                for at in range(1, successful_calls + 1):
                    result, calls, trace = call(mode, flag, fail_at=at)
                    assert result == -2 and calls == at and trace == full_trace[:at-1]
                    failures += 1
        for index in (4,65535):
            result,calls,trace=call(0,index=index)
            assert result==-1 and trace[-1]==(0,0xb550,index) and any(op==1 for op,a,v in trace)
        reports.append(dict(optimization=optimization, native_comparisons=len(cases),
                            invalid_modes=invalid, invalid_mode0_indices_after_writes=2, fail_stop_cases=failures))
    dependencies = [Path(__file__), ROOT / 'tools/verify/verify_rf_mode_native.py',
        ROOT / 'tools/verify/verify_rf_frequency_native.py', image_path, header, manifest,
        ROOT / 'firmware/rf_rebuild/rf_core_mode.h', *sources, *binaries]
    report = dict(status='passed', device_accessed=False, firmware_changed=False,
        deployed=False, scope='Original RF mode helper vs compiled ARM C; exact45 halfword writes and immediate bus-failure stop. Synthetic register states, seven legacy PULP operations modeled.',
        native_entry='0x3a7c', builds=reports,
        digital_flag_condition='exactly1 preserves32000 upperbyte and masks32004; other values use native fallback',
        physical_sample_rate_proved=False, filter_response_proved=False,
        dependencies={p.relative_to(ROOT).as_posix(): sha(p) for p in dependencies})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
