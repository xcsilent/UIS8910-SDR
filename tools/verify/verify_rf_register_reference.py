"""Offline RF address crosswalk: pinned reference declarations vs local rebuild.

Compiles reference layout/bitfield fixtures for ARM; never opens a device.
Unmatched addresses remain unnamed. This is not a silicon or PLL-lock test.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/host-test-deps'))
from elftools.elf.elffile import ELFFile

REFERENCE = ROOT / 'inputs/reference-source/zw217-uix8910'
PLATFORM = REFERENCE / 'chip_drv/chip_plf/uix8910'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def declarations(path, structure, prefix):
    """Check sequential REG32 layout, comments, and union bit widths."""
    text = path.read_text(encoding='utf-8')
    body = re.search(r'typedef volatile struct\s*\{(.*?)\}\s*' + structure, text, re.S)[1]
    result = {}
    offset = 0
    for line in body.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*REG32\s+(\w+)(?:\[(\d+)\])?;\s*//0x([\da-fA-F]+)\s*', line)
        if not match:
            raise ValueError('unparsed member: ' + line)
        name, count, comment = match.groups()
        assert offset == int(comment, 16), (name, hex(offset), comment)
        if not name.startswith('Reserved_'):
            result[offset] = dict(name=name, fields=[])
        offset += 4 * int(count or 1)
    for match in re.finditer(r'typedef union\s*\{(.*?)\}\s*(' + prefix + r'\w+_T);', text, re.S):
        body, typename = match.groups()
        name = typename[len(prefix):-2].lower()
        row = next((r for r in result.values() if r['name'].lower() == name), None)
        if row is None:
            continue
        shift = 0
        for field in re.finditer(r'REG32\s+(\w+)\s*:\s*(\d+);([^\n]*)', body):
            field_name, width, comment = field.groups()
            width = int(width)
            span = re.search(r'\[(\d+)(?::(\d+))?\]', comment)
            if span:
                high, low = int(span[1]), int(span[2] or span[1])
                assert (low, high) == (shift, shift + width - 1), field.group()
            if not field_name.startswith('__'):
                row['fields'].append(dict(name=field_name, lsb=shift, width=width,
                                         mask=hex(((1 << width) - 1) << shift)))
            shift += width
        assert shift == 32, (typename, shift)
        row['union_type'] = typename
    return result, offset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'records/rf/reference-rf-register-crosswalk.json')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT):
        parser.error('output must be inside project')
    manifest_path = REFERENCE / 'source-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    headers = [PLATFORM / n for n in ('rf_registers.h', 'cp_sysreg.h', 'globals.h')]
    for path in headers:
        entry = next(x for x in manifest['files'] if x['path'] == path.relative_to(REFERENCE).as_posix())
        raw = path.read_bytes()
        assert entry['upstream_blob_match'] and digest(path) == entry['sha256']
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == entry['git_blob_sha1']
    rf, rf_size = declarations(headers[0], 'HWP_RF_REGISTERS_T', 'REG_RF_REGISTERS_')
    mux, mux_size = declarations(headers[1], 'HWP_CP_SYSREG_T', 'REG_CP_SYSREG_')
    globals_text = headers[2].read_text(encoding='utf-8')
    assert re.search(r'#define\s+RF_NB_BITS_PADDR\s+\(12\)', globals_text)
    blocks = {name: int(value, 16) for name, value in
              re.findall(r'\bRF_APB_ID_(\w+)\s*=\s*(0x[\da-fA-F]+)', globals_text)}

    sources = sorted((ROOT / 'firmware/rf_rebuild').glob('rf_core_*.c'))
    uses = {}
    for path in sources:
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for literal in re.findall(r'\b0x[\da-fA-F]+', line):
                address = int(literal, 16)
                space = 'rf_local'
                if 0x50030000 <= address < 0x5003d000:
                    address -= 0x50000000
                    space = 'cp_view'
                if 0x30000 <= address < 0x3d000:
                    uses.setdefault(address, []).append(dict(source=path.relative_to(ROOT).as_posix(),
                        line=number, kind='source_literal', space=space))
    mode = ROOT / 'firmware/rf_rebuild/rf_core_mode.c'
    mode_text = mode.read_text(encoding='utf-8')
    table = re.search(r'offsets\[43\]\s*=\s*\{(.*?)\}', mode_text, re.S)[1]
    offsets = [int(n, 16) for n in re.findall(r'0x[\da-fA-F]+', table)]
    assert len(offsets) == 43 and re.search(r'0x32000u\s*\+\s*offsets\[i\]', mode_text)
    for n in offsets:
        uses.setdefault(0x32000 + n, []).append(dict(source=mode.relative_to(ROOT).as_posix(),
            kind='expanded_mode_offset_table', space='rf_local'))

    trace = ROOT / 'firmware/capture/rxcapt_rf_status_trace.h'
    trace_text=trace.read_text(encoding='utf-8')
    trace_reads = [(int(n), int(a, 16)) for n, a in
                   re.findall(r'R(16|32)\(0x([\da-fA-F]+)u\)', trace_text)]
    legacy_addresses={int(a,16) for a in re.findall(r'R(?:16|32)\(0x([\da-fA-F]+)u\)',trace_text.split('    row[8]')[0])}
    assert (16, 0x5003037c) in trace_reads
    trace_addresses = {a for n, a in trace_reads}
    candidate_only = {0x30324, 0x30354, 0x3036c}
    addresses = sorted(set(uses) | candidate_only | {a - 0x50000000 for n, a in trace_reads})
    rows = []
    selected = {}
    for address in addresses:
        offset = address - 0x30000
        declaration = rf.get(offset)
        block = next((name for name, index in blocks.items() if index == offset // 0x1000), None)
        row = dict(rf_local=hex(address), cp_view=hex(0x50000000 + address),
                   uses=uses.get(address, []), trace_read=(0x50000000 + address in trace_addresses))
        row['trace_abis']=[1,2] if 0x50000000+address in legacy_addresses else [2] if 0x50000000+address in trace_addresses else []
        if address < 0x30000:
            row.update(kind='rf_runtime_ram', reference_name=None)
        else:
            row.update(kind='rf_register', block=block, reference_name=declaration['name'] if declaration else None)
        if declaration:
            row['fields'] = declaration['fields']
            row['reference_gge_view'] = hex(0x05030000 + offset)
            row['reference_only_candidate'] = address in candidate_only and address not in uses
            selected[offset] = declaration
        rows.append(row)

    # ARM compiler checks actual offsetof and bitfield layout, not just comments.
    work = ROOT / 'work/rf-register-reference'
    work.mkdir(parents=True, exist_ok=True)
    fixture = work / 'layout.c'
    lines = ['#include <stdint.h>', '#include <stddef.h>', 'typedef uint32_t REG32;',
             '#define REG_ACCESS_ADDRESS(x) (x)', '#include "rf_registers.h"', '#include "cp_sysreg.h"',
             '_Static_assert(REG_RF_REG_BASE == EXPECT_RF_BASE, "RF base");',
             '_Static_assert(REG_SYSREG_BASE == EXPECT_MUX_BASE, "MUX base");',
             f'_Static_assert(sizeof(HWP_RF_REGISTERS_T)=={rf_size}, "RF size");',
             f'_Static_assert(sizeof(HWP_CP_SYSREG_T)=={mux_size}, "MUX size");']
    values = {}
    for structure, members in (('HWP_RF_REGISTERS_T', selected), ('HWP_CP_SYSREG_T', mux)):
        for offset, row in members.items():
            lines.append(f'_Static_assert(offsetof({structure},{row["name"]})=={offset}, "offset");')
            for field in row['fields']:
                symbol = 'field_' + row['name'] + '_' + field['name']
                all_bits = (1 << field['width']) - 1
                lines.append(f'const {row["union_type"]} {symbol} = {{.b.{field["name"]}={all_bits}u}};')
                values[symbol] = int(field['mask'], 16)
    fixture.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    gcc = ROOT / 'inputs/repositories/rda8910-csdk-hotelec/prebuilts/win32/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
    for gge in (False, True):
        obj = work / ('gge.o' if gge else 'cp.o')
        command = [str(gcc), '-std=c11', '-mcpu=cortex-a5', '-mthumb', '-ffreestanding', '-O2',
                   '-I' + str(PLATFORM), '-DEXPECT_RF_BASE=' + hex(0x05030000 if gge else 0x50030000),
                   '-DEXPECT_MUX_BASE=' + hex(0x05080000 if gge else 0x50080000),
                   '-c', str(fixture), '-o', str(obj)]
        if gge:
            command.append('-DREG_ADDRESS_FOR_GGE')
        subprocess.run(command, check=True, capture_output=True, text=True)
        with obj.open('rb') as stream:
            elf = ELFFile(stream)
            for symbol in elf.get_section_by_name('.symtab').iter_symbols():
                if symbol.name not in values:
                    continue
                section = elf.get_section(symbol['st_shndx'])
                start = symbol['st_value'] - section['sh_addr']
                actual = int.from_bytes(section.data()[start:start + 4], 'little')
                assert actual == values.pop(symbol.name), (symbol.name, hex(actual))
        assert not values, values
        # Re-use expectations in the other address-view build.
        values = {'field_' + r['name'] + '_' + f['name']: int(f['mask'], 16)
                  for r in list(selected.values()) + list(mux.values()) for f in r['fields']}

    recipe_path = ROOT / 'firmware/capture/build-recipe.json'
    recipe = json.loads(recipe_path.read_text(encoding='utf-8'))
    linked = sorted({x['path'] for cmd in recipe['commands'] for x in cmd if isinstance(x, dict)
                     and x['path'].startswith('firmware/rf_rebuild/') and x['path'].endswith('.c')})
    # A short B-specific native block: no guessed analog behavior or IO model.
    from verify_rf_frequency_native import Native
    from verify_rf_mode_native import X
    image_path = ROOT / 'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin/riscV.bin'
    image = image_path.read_bytes()
    assert image[0x4f7e:0x4f82] == bytes.fromhex('37040300')  # s0=0x30000
    assert image[0x4f86:0x4f88] == bytes.fromhex('156a')  # s4=0x5000
    native = Native(image, [])
    native.cpu.reg_write(X[8], 0x30000)
    native.cpu.reg_write(X[20], 0x5000)
    native.run(0x500a, {0x5040})
    expected_b = [(0x3041c, 0x11c0, 2), (0x30420, 0x5861, 2),
                  (0x30424, 0x7208, 2), (0x30408, 0x4845, 2)]
    assert native.writes == expected_b, native.writes
    dependencies = [Path(__file__), manifest_path, *headers, *sources, trace, recipe_path,
                    image_path, ROOT / 'tools/verify/verify_rf_frequency_native.py',
                    ROOT / 'tools/verify/verify_rf_mode_native.py']
    report = dict(status='passed', recorded_at=datetime.now().astimezone().isoformat(),
        device_accessed=False, firmware_changed=False, upstream_commit=manifest['commit'],
        scope='Reference declarations, ARM C layout, source address mentions and existing trace coverage only; not MMIO access authorization, silicon compatibility or physical PLL proof.',
        counts=dict(crosswalk_entries=len(rows), named_reference_entries=len(selected),
                    arm_bitfield_values_per_view=len(values), address_views_compiled=2),
        reference_block_roles={hex(0x30000 + 0x1000 * v): k for k, v in blocks.items()},
        registers=rows, capture_recipe_rf_sources=linked,
        native_b_prepare_fragment=dict(entry='0x500a', stop='0x5040',
            initial_registers={'s0': '0x30000', 's4': '0x5000'},
            context_source='Preceding original instructions at4f7e/4f86; bounded block only, not full initializer.',
            modeled_extensions=[], hardware_tested=False,
            writes=[dict(rf_local=hex(a), value=hex(v), bytes=n,
                         reference_name=rf[a-0x30000]['name']) for a, v, n in native.writes],
            conclusion='B analog writes are not a simple RX/TX PLL-address substitution of A prepare.'),
        trace_coverage=dict(reads_per_stage=len(trace_reads),reads_per_stage_by_abi={'1':len(legacy_addresses),'2':len(trace_reads)},
            tx_cal_status_in_trace=0x5003037c in trace_addresses,
            rx_cal_status_in_trace=0x5003036c in trace_addresses,
            bbpll_lock_in_trace=bool(trace_addresses & {0x50030324, 0x50030354}),
            warning='ABI1 deployedv16 observes A/TX status only; ABI2 candidate adds B/RX, route and BBPLL states. Reference names and observations do not independently prove RF LO lock.'),
        limitations=['Generic reg_XXX_bit fields are not decoded analog semantics.',
            'DFE32000..32fff is identified by the APB enum; this RF header has no member definitions for it.',
            'Header REG32 slots do not override native 16-bit accesses.',
            'GGE base is a reference build option, not proof of active device configuration.',
            'Source mentions are not an exhaustive dynamic access trace.'],
        dependencies={p.relative_to(ROOT).as_posix(): digest(p) for p in dependencies})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], **report['counts'], output=output.relative_to(ROOT).as_posix())))


if __name__ == '__main__':
    main()
