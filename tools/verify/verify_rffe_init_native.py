"""Execute the original RF initialization entry helper with retained NV.

This checks software MMIO writes only, not the RFFE controller or RF hardware.
"""
import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/host-test-deps'))
sys.path.insert(0, str(ROOT / 'tools/verify'))
from verify_rf_frequency_native import Native
from verify_rf_mode_native import X, PC
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_CODE
from elftools.elf.elffile import ELFFile
from elftools.dwarf.dwarf_expr import DWARFExprParser


class RffeNative(Native):
    def __init__(self, image, rules):
        self.observer_enabled=image[0x10e8:0x10ec]!=bytes.fromhex('83470500')
        self.observer_writes=[]
        super().__init__(image, rules)
        self.cpu.mem_map(0x3c000, 0x1000)

    def observe(self, cpu, access, address, size, value, context):
        if self.observer_enabled and address in (0x6118,0x611c):
            assert size==4
            self.observer_writes.append((address,value&0xffffffff))
        elif 0x3c000 <= address < 0x3d000:
            self.writes.append((address, value & ((1 << (size * 8)) - 1), size))
        else:
            super().observe(cpu, access, address, size, value, context)


def run_slice(machine, start, stop, defs, skip_delay=False):
    """Run a bounded slice, modeling the required pinned legacy operations.

    Only calls to the existing delay helper are omitted. This does not model
    physical wait duration, controller completion, ACK, or RF bus traffic.
    """
    cpu = machine.cpu
    pc = start
    delays = 0
    for steps in range(3000):
        if pc == stop:
            return dict(instructions=steps, omitted_delay_calls=delays)
        word = int.from_bytes(cpu.mem_read(pc, 4), 'little')
        if skip_delay and pc in (0x193c, 0x1950, 0x18aa, 0x18ec):
            # All four original JAL targets are 0x7a0 (delay wrapper).
            assert word & 0x7f == 0x6f
            disp = ((word >> 31) << 20) | (((word >> 12) & 255) << 12) | (((word >> 20) & 1) << 11) | (((word >> 21) & 1023) << 1)
            if disp & (1 << 20):
                disp -= 1 << 21
            assert pc + disp == 0x7a0
            cpu.reg_write(X[1], pc + 4)
            pc += 4
            delays += 1
            continue
        match = next((name for name, mask in [('EXTHZ', 'PALUS'), ('BSET', 'PALU2'), ('EXTRACTU', 'PALU2'), ('LWRR', 'LRR')]
                      if word & 3 == 3 and word & defs['MASK_' + mask] == defs['MATCH_' + name]), None)
        if match:
            rd, rs1, bit = (word >> 7) & 31, (word >> 15) & 31, (word >> 20) & 31
            value = cpu.reg_read(X[rs1]) if rs1 else 0
            if match == 'EXTHZ':value &= 65535
            elif match == 'BSET':value |= ((1 << (((word >> 25) & 31) + 1)) - 1) << bit
            elif match == 'EXTRACTU':value = (value >> bit) & ((1 << (((word >> 25) & 31) + 1)) - 1)
            elif match == 'LWRR':
                value = int.from_bytes(cpu.mem_read((value + (cpu.reg_read(X[bit]) if bit else 0)) & 0xffffffff,4),'little')
            if rd:
                cpu.reg_write(X[rd], value & 0xffffffff)
            cpu.reg_write(PC, pc + 4)
        else:
            cpu.emu_start(pc, 0x7ffffffe, count=1)
        pc = cpu.reg_read(PC)
    raise AssertionError('RFFE slice exceeded instruction budget')


def id_read_cases(image, rules, defs):
    results = []
    # IDs and ready delays are synthetic peripheral inputs, not device reads.
    for slave in (13, 14, 15):
        for manufacturer, product in ((0x9a, 0x96), (0x20, 0), (0xffff, 0xffff)):
            for readiness in ((0, 0), (2, 3), (None, 0), (0, None), (None, None)):
                class IdNative(RffeNative):
                    def observe(self, cpu, access, address, size, value, context):
                        if address == 0x3c004:
                            self.transaction += 1
                            self.polls = 0
                        if 0x96b0 <= address < 0x96f0:
                            return
                        super().observe(cpu, access, address, size, value, context)
                n = IdNative(image, rules)
                n.transaction = -1
                n.polls = 0
                def on_read(cpu, access, address, size, value, context):
                    if address == 0x3c018:
                        target = readiness[n.transaction]
                        ready = target is not None and n.polls >= target
                        n.polls += 1
                        cpu.mem_write(address, struct.pack('<H', int(ready)))
                    elif address == 0x3c010:
                        cpu.mem_write(address, struct.pack('<H', (manufacturer, product)[n.transaction]))
                n.cpu.hook_add(UC_HOOK_MEM_READ, on_read)
                n.cpu.mem_write(0xa7fa, bytes([slave]))
                n.cpu.reg_write(X[19], 0x4567)  # must be overwritten by the native slave load
                execution = run_slice(n, 0x185c, 0x190e, defs, skip_delay=True)
                values = struct.unpack('<3H', n.cpu.mem_read(0x96e4, 6))
                expected = (slave, manufacturer if readiness[0] is not None else 0,
                            product if readiness[1] is not None else 0)
                assert values == expected, (slave, readiness, values, expected)
                commands = [(a, v) for a, v, _ in n.writes if a in (0x3c000, 0x3c004)]
                assert commands == [(0x3c000, 0x1e), (0x3c004, (slave << 10) | 0x70),
                                    (0x3c000, 0x1d), (0x3c004, (slave << 10) | 0x70)], commands
                assert not n.observer_writes  # ID transactions do not enter the command helper
                results.append(dict(synthetic_slave=slave, supplied_ids=[manufacturer, product],
                                    ready_after_polls=readiness, saved_config_halfwords=values, **execution))
    return results


def target_nv_field(axf, raw):
    with axf.open('rb') as stream:
        dwarf = ELFFile(stream).get_dwarf_info()
        parser = DWARFExprParser(dwarf.structs)
        for cu in dwarf.iter_CUs():
            for die in cu.iter_DIEs():
                name = die.attributes.get('DW_AT_name')
                if name and name.value == b'rf_lte_nv_fem_mipi_tag':
                    offsets = {}
                    for child in die.iter_children():
                        attr = child.attributes.get('DW_AT_name')
                        if attr and attr.value in (b'mipi_init', b'rx_mipi_sw_open', b'gsm_tx_mipi_sw_open'):
                            expr = parser.parse_expr(child.attributes['DW_AT_data_member_location'].value)
                            assert len(expr) == 1 and expr[0].op_name == 'DW_OP_plus_uconst'
                            offsets[attr.value.decode()] = expr[0].args[0]
                    assert offsets == dict(mipi_init=0, rx_mipi_sw_open=100, gsm_tx_mipi_sw_open=0x10ac)
                    assert 0x974c + offsets['gsm_tx_mipi_sw_open'] + 2 == 0xa7fa
                    return dict(dwarf_type='rf_lte_nv_fem_mipi_tag', field='gsm_tx_mipi_sw_open[0].byte2',
                                member_offsets=offsets, rf_local_address='0xa7fa',
                                nv_offset='0x135a', retained_snapshot_value=raw[0x135a],
                                scope='Read target comes from the first GSM TX-switch NV entry, not the LTE request selector. This names a config byte, not live bus traffic or GSM decoding.')
    raise AssertionError('FEM DWARF type not found')


def rx_switch_cases(image, raw, rules, defs):
    cases=[]
    # Retained board selector/NV row combinations. The map is supplied, not
    # inferred by this test or treated as a live RF RAM table observation.
    for band,selector,row in ((3,2,2),(5,4,4),(8,6,6),(40,15,22)):
        assert struct.unpack_from('<H',raw,0x20+2*row)[0]==band
        for operation,offset in enumerate((0x310,0x490,0x610,0x790)):
            for enabled in (0,1):
                n=RffeNative(image,rules)
                retained_writes=[]
                command_entries=[]
                def retained_write(cpu,access,address,size,value,context):
                    if address<0x10000:
                        if n.observer_enabled and address in (0x6118,0x611c):return
                        retained_writes.append(dict(address=hex(address),bytes=size,value=hex(value)))
                n.cpu.hook_add(UC_HOOK_MEM_WRITE,retained_write)
                def command_entry(cpu,address,size,context):
                    if address==0x10e8:
                        command_entries.append(cpu.reg_read(X[10]))
                n.cpu.hook_add(UC_HOOK_CODE,command_entry)
                n.cpu.mem_write(0x974c,raw[0x2ac:0x1428])
                n.cpu.mem_write(0x940c+selector*2,struct.pack('<H',row))
                n.cpu.mem_write(0xaf74,struct.pack('<H',enabled))
                n.cpu.reg_write(X[10],0x8000|(selector<<4)|operation)
                run_slice(n,0x7140,0xf000,defs)
                commands=[]
                if enabled and any(raw[offset+row*16:offset+row*16+4]):
                    for i in range(4):
                        entry=raw[offset+row*16+i*4:offset+row*16+i*4+4]
                        if any(entry):
                            value,reg,slave,reserved=entry
                            commands.extend([(0x3c008,value,2),(0x3c000,reg,2),
                                             (0x3c004,((slave<<10)|0x72)&65535,2)])
                assert n.writes==commands,(band,operation,enabled,n.writes,commands)
                assert not retained_writes,retained_writes
                assert len(command_entries)==len(commands)//3
                if n.observer_enabled:
                    count,last=struct.unpack('<2I',n.cpu.mem_read(0x6118,8))
                    assert count==len(command_entries)
                    assert last==(command_entries[-1] if command_entries else 0)
                cases.append(dict(band=band,selector=selector,nv_row=row,operation=operation,
                    synthetic_enable=enabled,command_count=len(commands)//3,
                    command_helper_arguments=[hex(v) for v in command_entries],
                    retained_rf_ram_writes=retained_writes,
                    controller_writes=[dict(address=hex(a),value=hex(v),bytes=w) for a,v,w in commands]))
    return cases


def observer_abi_cases(original,image,rules):
    results=[]
    for initial_count in (0,17,0xffffffff):
        for word in (0x000d0005,0x000f0200,0x00ffffff):
            machines=[RffeNative(raw,rules) for raw in (original,image)]
            for machine in machines:
                for register in range(1,32):machine.cpu.reg_write(X[register],0xa5000000+register*256)
                machine.cpu.reg_write(X[1],0xf000);machine.cpu.reg_write(X[2],0x108000)
                machine.cpu.reg_write(X[10],0x974c)
                machine.cpu.mem_write(0x974c,struct.pack('<I',word))
                if machine.observer_enabled:machine.cpu.mem_write(0x6118,struct.pack('<2I',initial_count,0xdeadbeef))
                stop,_=machine.run(0x10e8,{0xf000});assert stop==0xf000
            before,after=machines
            assert before.writes==after.writes
            assert [before.cpu.reg_read(r) for r in X]==[after.cpu.reg_read(r) for r in X]
            assert struct.unpack('<2I',after.cpu.mem_read(0x6118,8))==((initial_count+1)&0xffffffff,0x974c)
            assert len(after.observer_writes)==2
            results.append(dict(initial_counter=initial_count,command_word=hex(word),all_registers_match=True,controller_writes_match=True))
    bypass=RffeNative(image,rules)
    seed=struct.pack('<2I',17,0x974c);bypass.cpu.mem_write(0x6118,seed)
    bypass.cpu.emu_start(0x60f6,0x6122,count=10)
    assert bypass.cpu.reg_read(PC)==0x6122 and bytes(bypass.cpu.mem_read(0x6118,8))==seed
    assert not bypass.writes and not bypass.observer_writes
    return dict(helper_cases=results,rxon_fallthrough_skips_code_and_data=True,
                scope='All32 registers and ordered controller writes compared at helper return; synthetic instruction execution, no controller timing/ACK or deployment proof.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current-pac',action='store_true',help='execute the verified decoded current PAC RF image instead of the SDK reference')
    parser.add_argument('--observer-build',type=Path,help='verify an offline RF observer against its current PAC parent')
    args=parser.parse_args()
    if args.current_pac and args.observer_build:parser.error('choose current-pac or observer-build')
    sdk = ROOT / 'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin/riscV.bin'
    cp=sdk; provenance=[]
    baseline=None
    if args.current_pac or args.observer_build:
        from rf_image import current_pac_image
        cp,provenance=current_pac_image()
    if args.observer_build:
        baseline=cp.read_bytes();observer_build=args.observer_build.resolve()
        candidate=json.loads(observer_build.read_text())
        assert hashlib.sha256(baseline).hexdigest()==candidate['parent_image_sha256']
        for name,digest in candidate['dependencies'].items():
            assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
        cp=ROOT/candidate['image']
        assert hashlib.sha256(cp.read_bytes()).hexdigest()==candidate['image_sha256']
        provenance+=[observer_build,*[ROOT/name for name in candidate['dependencies']]]
    nv = ROOT / 'records/rf/runtime-frontend-current.rfnv.bin'
    header = ROOT / 'inputs/reference-source/riscv-pulp-legacy/riscv-opc.h'
    manifest = header.parent / 'source-manifest.json'
    pinned = json.loads(manifest.read_text())
    assert hashlib.sha256(header.read_bytes()).hexdigest() == next(row['sha256'] for row in pinned['files'] if row['file'] == header.name)
    defs = {k: int(v, 16) for k, v in re.findall(r'#define\s+((?:MATCH|MASK)_\w+)\s+(0x[0-9a-fA-F]+)', header.read_text())}
    rules = [(n, defs['MATCH_' + n], defs['MASK_' + m]) for n, m in
             [('EXTHZ', 'PALUS'), ('BCLR', 'PALU2'), ('BNEM1', 'BNEM1')]]
    raw = nv.read_bytes()
    rows = []
    for i, word in enumerate(struct.unpack_from('<25I', raw, 0x2ac)):
        if not word:
            continue
        data, reg, slave, reserved = struct.pack('<I', word)
        machine = RffeNative(cp.read_bytes(), rules)
        machine.cpu.mem_write(0x974c, struct.pack('<I', word))
        machine.cpu.reg_write(X[10], 0x974c)
        stop, _ = machine.run(0x10e8, {0xf000})
        expected = [(0x3c008, data, 2), (0x3c000, reg, 2),
                    (0x3c004, ((slave << 10) | 0x72) & 0xffff, 2)]
        assert stop == 0xf000 and machine.writes == expected, (i, machine.writes, expected)
        if args.observer_build:assert struct.unpack('<2I',machine.cpu.mem_read(0x6118,8))==(1,0x974c)
        rows.append(dict(index=i, nv_word=hex(word), value=data, register=reg, slave=slave,
                         reserved=reserved, writes=[dict(address=hex(a), value=hex(v), bytes=n) for a, v, n in expected]))
    assert len(rows) == 8
    # Execute the original loop as well, with unmodified zero slots and limits.
    loop = RffeNative(cp.read_bytes(), rules)
    loop.cpu.mem_write(0x974c, raw[0x2ac:0x310])
    run_slice(loop, 0x1960, 0x185c, defs)
    assert loop.writes == [(int(w['address'], 16), int(w['value'], 16), w['bytes'])
                           for row in rows for w in row['writes']]
    if args.observer_build:assert struct.unpack('<I',loop.cpu.mem_read(0x6118,4))[0]==8
    disabled = RffeNative(cp.read_bytes(), rules)
    disabled.cpu.mem_write(0x974c, b'\0' * 4 + raw[0x2b0:0x310])
    run_slice(disabled, 0x183a, 0x185c, defs)
    assert not disabled.writes  # zero first entry bypasses the entire init list
    ids = id_read_cases(cp.read_bytes(), rules, defs)
    switches=rx_switch_cases(cp.read_bytes(),raw,rules,defs)
    observer_tests=observer_abi_cases(baseline,cp.read_bytes(),rules) if args.observer_build else None
    axf = sdk.with_name('cp.axf')
    field = target_nv_field(axf, raw)
    reference_root=ROOT/'inputs/repositories/ZW217_W19_V4.1_yisai'
    loader=reference_root/'chip_drv/chip_module/chip/uix8910/load_modem.c'
    loader_header=loader.with_suffix('.h')
    bases=reference_root/'chip_drv/chip_plf/uix8910/uix8910_reg_base.h'
    source=loader.read_text(encoding='utf-8',errors='replace')
    branch=source[source.index('if(strcmp((char *)pt_mem_list->index_unit[i].name, MEM_RISCV_BIN_NAME)'):]
    reset='CHIP_REG_AND(((RF_ISRAM_BASE)+0x35008),(~0x10))'
    load='MEM_bzpLoad(LZMA_BZP_EX04,'
    assert 0<=branch.index(reset)<branch.index(load)
    assert re.search(r'#define\s+RF_ISRAM_BASE\s+0x50000000',bases.read_text())
    assert re.search(r'#define\s+MEM_RISCV_BIN_NAME\s+"riscV.bin"',loader_header.read_text())
    assert 'unzip_data_len > load_len' in source and '(uint32)load_addr%8!=0' in source
    assert 'if(idx==LZMA_BZP_EX01 || idx==LZMA_BZP_EX02 )' in source
    assert 'memcpy(load_addr,in.zip_buf_addr,in.zip_buf_len)' in source
    dependencies = [Path(__file__), cp, axf, nv, header, manifest, ROOT/'tools/verify/verify_rf_frequency_native.py',
                    ROOT/'tools/verify/verify_rf_mode_native.py',loader,loader_header,bases]
    dependencies+=provenance
    report = dict(status='passed', device_accessed=False, hardware_tested=False,
                  image_source='offline RF observer candidate' if args.observer_build else ('current PAC decoded payload' if args.current_pac else 'SDK reference RF binary'),
                  image_sha256=hashlib.sha256(cp.read_bytes()).hexdigest(),
                  observer_verification=observer_tests,
                  scope='Native helper/init-loop execution plus synthetic ID-read control flow and DWARF target mapping. No actual RFFE peripheral, bus transaction, USID change or hardware identity verified.',
                  original_init_loop_matches=True, zero_first_entry_bypasses_init_list=True,
                  synthetic_id_read_cases=ids,
                  id_target_field=field,
                  reference_image_loader=dict(platform='ZW217 uix8910',function='LOAD_modem',
                      entry_name='riscV.bin',compressed_entry='LZMA_BZP_EX04',
                      pre_load_register='0x50035008',pre_load_clear_mask='0x10',
                      destination='memory-index entry addr/len, not a hardcoded destination inferred here',
                      source_checks=['8-byte destination alignment','decompressed length <= destination length'],
                      active_reference_branch='Under #if0 alternative, load_use_lzma true decodes EX01/EX02 only; EX04 follows memcpy. EX04 accessor representation and current SDK loader remain unresolved.',
                      scope='Reference source text relation only; not compiled control-flow proof or current UIS8910 SDK/AP identity. Reset meaning comes from source comment; no hardware writes.'),
                  retained_board_rx_switch_cases=switches,
                  rx_switch_scope='Native 0x7140 dispatcher, selector map940c and four-entry helper6712 to helper10e8. Retained board NV and injected selector map/enable; observer builds additionally write their declared count/pointer. No other retained RAM writes in these cases; not actual RF RAM, RFAD delivery or wire/port/reception proof.',
                  id_read_scope='Native 0x185c..0x190e with synthetic ready/result MMIO; delay wrapper calls omitted, no physical timing/ACK modeled. Reads 1e then1d, ctrl=(slave<<10)|0x70; timeout saves zero, no ID acceptance comparison in this slice.',
                  rows=rows, dependencies={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies})
    path=ROOT/('records/rf/reference-rffe-observer-native.json' if args.observer_build else ('records/rf/reference-rffe-current-pac-native.json' if args.current_pac else 'records/rf/reference-rffe-init-native.json'))
    path.write_text(json.dumps(report, indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=report['status'], init_entries=len(rows),
                          original_init_loop_matches=True, synthetic_id_read_cases=len(ids),
                          retained_rx_switch_cases=len(switches),
                          output=path.relative_to(ROOT).as_posix()), indent=2))


if __name__ == '__main__':
    main()
