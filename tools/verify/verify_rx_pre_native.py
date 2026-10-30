"""Check RX_PRE_CFG DWARF and original CP update/DAGC instructions offline.

This verifies register fields and software writes, not physical filter enables,
sample-clock frequencies, ADC resolution, or changes to DMA sample packing.
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/host-test-deps'))
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R4, UC_ARM_REG_R5,
    UC_ARM_REG_R6, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
)

SDK = ROOT / 'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin'
BASE = 0x801ab000
REG = 0x25000038


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'work/rx-pre-native.json')
    args = parser.parse_args()
    cp, axf = SDK / 'cp.bin', SDK / 'cp.axf'
    blob = cp.read_bytes()
    with axf.open('rb') as file:
        elf = ELFFile(file)
        assert elf.little_endian
        symbols = {s.name: s for s in elf.get_section_by_name('.symtab').iter_symbols()}

        def code(name):
            sym = symbols[name]
            section = elf.get_section(sym['st_shndx'])
            offset = (sym['st_value'] & ~1) - section['sh_addr']
            return section.data()[offset:offset + sym['st_size']]

        fields, register_offset, dwarf_source = {}, None, None
        for cu in elf.get_dwarf_info().iter_CUs():
            for die in cu.iter_DIEs():
                attr = die.attributes.get('DW_AT_name')
                name = attr.value if attr else None
                if name == b'RX_BITSEL':
                    parent = die.get_parent()
                    assert parent.attributes['DW_AT_byte_size'].value == 4
                    dwarf_source = cu.get_top_DIE().attributes['DW_AT_name'].value.decode()
                    for member in parent.iter_children():
                        a = member.attributes
                        width = a['DW_AT_bit_size'].value
                        lsb = 32 - a['DW_AT_bit_offset'].value - width
                        fields[a['DW_AT_name'].value.decode()] = dict(lsb=lsb, width=width)
                if name == b'RX_PRE_CFG' and die.tag == 'DW_TAG_member':
                    expression = die.attributes['DW_AT_data_member_location'].value
                    assert expression == [0x23, 0x38]  # DW_OP_plus_uconst 56
                    register_offset = 0x38
            if fields and register_offset is not None:
                break
        expected = {'RX_BITSEL': (0, 5), 'FIR_EN': (6, 1),
                    'FREQ_EN': (7, 1), 'RX_BW_SEL': (8, 3), 'RX_FREQ_FACTOR': (12, 11)}
        for name, (lsb, width) in expected.items():
            assert fields[name] == dict(lsb=lsb, width=width)
        update = code('algo_lte_hw_txrx_rx_update')
        setter = code('l1cc_lte_set_dagc')
        # Native arithmetic after the measurement helpers return, through stores.
        # Helpers are outside this test: input is their already computed delta.
        clamp = code('l1cc_lte_dagc_cal')[0x42:0x64]

    copier, source, destination, length = struct.unpack_from('<4I', blob, 0x2bc4dc)
    assert (copier, source, destination, length) == (0x8025b8e8, 0x804750bc, 0x804000, 0x29724)

    def entry(pattern, prefix=0):
        assert blob.count(pattern) == 1
        offset = blob.find(pattern) - prefix
        assert source - BASE <= offset < source - BASE + length
        return destination + offset - (source - BASE)

    update_pc = entry(update)
    setter_pc = entry(setter[2:], 2)  # first PC-relative literal differs in BIN
    clamp_pc = entry(clamp)
    # Read the actual BIN literal used by l1cc_lte_set_dagc, not ELF globals.
    ram = blob[source - BASE:source - BASE + length]
    first = struct.unpack_from('<H', ram, setter_pc - destination)[0]
    assert first & 0xf800 == 0x4800
    literal = ((setter_pc + 4) & ~3) + (first & 255) * 4
    dagc = struct.unpack_from('<I', ram, literal - destination)[0]
    assert 0x80400000 <= dagc < 0x80500000

    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.mem_map(0x80000000, 0x1000000)
    cpu.mem_write(BASE, blob)
    cpu.mem_map(0x800000, 0x40000)
    cpu.mem_write(destination, ram)
    cpu.mem_map(0x25000000, 0x1000)
    cpu.mem_map(0x70000000, 0x1000)
    writes = []
    cpu.hook_add(UC_HOOK_MEM_WRITE, lambda uc, access, address, size, value, data:
                 writes.append((address, size, value)) if 0x25000000 <= address < 0x25001000 else None)

    def put(address, value):
        cpu.mem_write(address, struct.pack('<I', value & 0xffffffff))

    def get(address):
        return struct.unpack('<I', cpu.mem_read(address, 4))[0]

    def execute(pc, stop=0x70000000):
        writes.clear()
        cpu.reg_write(UC_ARM_REG_SP, 0x8097f000)
        cpu.reg_write(UC_ARM_REG_LR, 0x70000001)
        cpu.emu_start(pc | 1, stop, count=100)
        assert cpu.reg_read(UC_ARM_REG_PC) == stop

    updater_cases = []
    context = 0x80900000
    for bw in range(6):
        for matching in (False, True):
            values = [0x12340000 + n for n in range(9)]
            values[0] = 123
            values[7] = bw << 8 | 8
            cpu.mem_write(context, struct.pack('<9I', *values))
            put(REG, 0xdeadbeef)
            cpu.reg_write(UC_ARM_REG_R0, 123 if matching else 124)
            cpu.reg_write(UC_ARM_REG_R1, context)
            execute(update_pc)
            assert get(REG) == (values[7] if matching else 0xdeadbeef)
            assert len(writes) == (6 if matching else 0)
            updater_cases.append(dict(bandwidth_index=bw, context_matches=matching,
                                      rx_pre_cfg=hex(get(REG)), mmio_writes=len(writes)))

    setter_cases = 0
    for bw in range(6):
        for flags in (0, 0x40, 0x80, 0xc0):
            for bitsel in range(19):
                for active in (0, 1):
                    original = 0xa5500000 | 0x123000 | bw << 8 | flags | 8
                    put(REG, original)
                    put(dagc, active)
                    put(dagc + 4, 0x87654321)
                    put(dagc + 8, bitsel)
                    execute(setter_pc)
                    expected_value = original & ~31 | bitsel if active else original
                    assert get(REG) == expected_value
                    assert writes == ([(REG, 4, expected_value)] if active else [])
                    setter_cases += 1

    clamp_cases = []
    for old in range(19):
        for delta in (-100, -19, -1, 0, 1, 19, 100):
            put(dagc + 8, 0xabcdef00)
            cpu.reg_write(UC_ARM_REG_R0, delta & 0xffffffff)
            cpu.reg_write(UC_ARM_REG_R6, old)
            cpu.reg_write(UC_ARM_REG_R5, dagc)
            cpu.reg_write(UC_ARM_REG_R4, context)
            execute(clamp_pc, clamp_pc + len(clamp))
            result = min(18, max(0, old + delta))
            assert get(dagc + 8) == 0xabcdef00 | result
            assert get(dagc) & 0xffff == 1
            assert not writes
            clamp_cases.append(dict(previous_bitsel=old, measurement_delta=delta, result=result))

    dependencies = [Path(__file__), cp, axf, ROOT / 'firmware/rf_rebuild/rfad_raw_capture.c']
    report = dict(status='passed', device_accessed=False, hardware_tested=False,
        scope='DWARF register fields and actual BIN update/DAGC setter/clamp instructions; synthetic memory and MMIO',
        dwarf_source=dwarf_source, register_address=hex(REG), fields=fields,
        native_entries=dict(update=hex(update_pc), dagc_setter=hex(setter_pc), dagc_clamp_slice=hex(clamp_pc)),
        native_dagc_context=hex(dagc), updater_cases=updater_cases,
        setter_cases=setter_cases, clamp_cases=clamp_cases,
        current_direct_profile=dict(rx_bitsel=8, fir_en=0, freq_en=0, rx_bw_sel='requested BW index'),
        conclusions=[
            'RX_BITSEL is a five-bit value adjusted by native DAGC arithmetic and clamped0..18, not a declaration of stored sample width.',
            'Native DAGC setter modifies only bits4:0 and preserves BW/FIR/FREQ/factor and reserved bits.',
            'Current direct RX_PRE_CFG write leaves this register FIR_EN/FREQ_EN clear. A coefficient copy does not demonstrate this stage is enabled.',
            'Separate RF-core mode/filter programming is retained in vendor initialization; this test does not identify the physical decimation or sample clock.',
            'No new sample-rate, passband, ENOB or compact8-bit transfer capability is established.'
        ],
        dependencies={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status='passed', output=str(args.output), update_cases=len(updater_cases),
                          setter_cases=setter_cases, clamp_cases=len(clamp_cases))))


if __name__ == '__main__':
    main()
