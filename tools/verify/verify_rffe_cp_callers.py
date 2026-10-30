"""Resolve CP RFFE switch helpers and their direct and veneer call sites.

Checks static calls and bounded native fragments with synthetic state; it does
not establish device execution or bus activity.
"""
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CP = ROOT / 'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin/cp.axf'
CP_BIN = CP.with_name('cp.bin')
OBJDUMP = ROOT / 'inputs/repositories/rda8910-csdk-hotelec/prebuilts/win32/gcc-arm-none-eabi/bin/arm-none-eabi-objdump.exe'


def main():
    dis = subprocess.check_output([str(OBJDUMP), '-d', str(CP)], text=True)
    # ARM veneers execute ldr pc,[pc,#-4] and contain Thumb target|1.
    for address, target in [('81b50c', '801f2d21'), ('81b4bc', '802c3305')]:
        assert re.search(rf'^\s*{address}:\s+e51ff004\s+ldr\s+pc,\s*\[pc,\s*#-4\]', dis, re.M)
        assert re.search(rf'^\s*{int(address, 16)+4:x}:\s+{target}\s+\.word', dis, re.M)
    current = None
    sites = []
    rxon_calls=[];agc_callers=[]
    for line in dis.splitlines():
        header = re.match(r'^([0-9a-f]+) <([^>]+)>:', line)
        if header:
            current = header.group(2)
        call = re.match(r'^\s*([0-9a-f]+):\s+(?:[0-9a-f]+\s+)+blx?\s+([0-9a-f]+)\s+<', line)
        if not call:
            continue
        address, target = call.groups()
        if target in ('80677a','8062c4'):
            rxon_calls.append(dict(caller=current,address='0x'+address,target='0x'+target))
        if target=='805250':agc_callers.append(dict(caller=current,address='0x'+address))
        helper = {'81b50c': 'swon', '81b4bc': 'swoff', '801f2d20': 'swon', '802c3304': 'swoff'}.get(target)
        if helper:
            sites.append(dict(caller=current, address='0x'+address, target='0x'+target, helper=helper))
    expected = {('0x80637e', 'swon'), ('0x80647a', 'swon'), ('0x806584', 'swon'),
                ('0x806824', 'swon'), ('0x806924', 'swon'), ('0x806afc', 'swoff'),
                ('0x801ed750', 'swoff'), ('0x801ed7aa', 'swoff'), ('0x801fa514', 'swoff')}
    assert {(x['address'], x['helper']) for x in sites} == expected, sites
    assert {x['address'] for x in rxon_calls}=={'0x804ee8','0x804eee','0x8052d4','0x8052da'}
    assert {x['caller'] for x in agc_callers}=={'algo_lte_iddet_txrx_agc_cal','l1cc_lte_ncell_agc_cal','l1cc_lte_datapro_ip_update','l1cc_lte_iddet_int_hisr','l1cc_lte_txrx_int_hisr'}
    # A nearby literal-pool annotation can name another function; use the
    # ELF function boundaries, not that annotation, for attribution.
    from elftools.elf.elffile import ELFFile
    with CP.open('rb') as stream:
        elf = ELFFile(stream)
        symbols = elf.get_section_by_name('.symtab')
        for site in sites:
            addr = int(site['address'], 16)
            matches = [s for s in symbols.get_symbol_by_name(site['caller']) or []
                       if s['st_info']['type'] == 'STT_FUNC' and
                       (s['st_value'] & ~1) <= addr < (s['st_value'] & ~1) + s['st_size']]
            assert matches, site
        event = symbols.get_symbol_by_name('rf_lte_event_req')[0]
        section = elf.get_section(event['st_shndx'])
        elf_address = event['st_value'] & ~1
        elf_code = section.data()[elf_address-section['sh_addr']:elf_address-section['sh_addr']+event['st_size']]
        cp_blob = CP_BIN.read_bytes()
        bound_offset = 0x802d0720 - 0x801ab000
        bound_code = cp_blob[bound_offset:bound_offset+len(elf_code)]
        matches = sum(a == b for a, b in zip(elf_code, bound_code))
        assert len(elf_code) == 0x278 and len(bound_code) == len(elf_code)
        assert matches == 587 and elf_code[:4] == bound_code[:4]
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
        decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        old_insn = {i.address-elf_address: i for i in decoder.disasm(elf_code, elf_address)}
        new_insn = {i.address-0x802d0720: i for i in decoder.disasm(bound_code, 0x802d0720)}
        changed = [offset for offset in old_insn.keys() & new_insn.keys()
                   if old_insn[offset].bytes != new_insn[offset].bytes]
        assert len(changed) == 31
        assert all(old_insn[offset].mnemonic == new_insn[offset].mnemonic for offset in changed)
        assert (old_insn[0x14c].op_str, new_insn[0x14c].op_str) == ('#0x802b0882', '#0x802d043a')
        assert (old_insn[0x196].op_str, new_insn[0x196].op_str) == ('#0x802b07ea', '#0x802d039a')
        comparison = dict(elf_symbol='rf_lte_event_req', elf_address=hex(elf_address),
                          cp_bin_offset=hex(bound_offset), assumed_linear_runtime_address='0x802d0720',
                          bytes=len(elf_code), equal_bytes=matches, changed_decoded_instructions=len(changed),
                          changed_mnemonics=0,
                          examples=[dict(offset='0x14c',elf_target='0x802b0882',elf_symbol='rf_get_freq',cp_bin_target='0x802d043a'),
                                    dict(offset='0x196',elf_target='0x802b07ea',elf_symbol='rf_lte_get_semseg',cp_bin_target='0x802d039a')],
                          limitation='High similarity is not byte identity or proof of deployed PAC contents/runtime mapping; differing instructions require separate analysis.')
        import struct
        scatter = struct.unpack_from('<4I', cp_blob, 0x2bc4dc)
        assert scatter == (0x8025b8e8, 0x804750bc, 0x804000, 0x29724)
        def scatter_bytes(address, size):
            _, source, destination, length = scatter
            assert destination <= address and address + size <= destination + length
            offset = source - 0x801ab000 + address - destination
            return cp_blob[offset:offset+size]
        mapped_calls = []
        for site in sites:
            if not site['address'].startswith('0x806'):
                continue
            runtime_address = int(site['address'], 16) + 0x40
            ins = list(decoder.disasm(scatter_bytes(runtime_address, 4), runtime_address))
            assert len(ins) == 1 and ins[0].mnemonic == 'blx'
            target = int(ins[0].op_str.lstrip('#'), 16)
            assert target == (0x81b598 if site['helper'] == 'swon' else 0x81b548)
            veneer = scatter_bytes(target, 8)
            assert veneer[:4] == bytes.fromhex('04f01fe5')
            destination = int.from_bytes(veneer[4:], 'little')
            assert destination == (0x8020306d if site['helper'] == 'swon' else 0x802d3fcd)
            mapped_calls.append(dict(elf_call=site['address'], caller=site['caller'], helper=site['helper'],
                                     bin_runtime_call=hex(runtime_address), veneer=hex(target), helper_target=hex(destination)))
        def linear_bytes(address, size):
            offset = address - 0x801ab000
            return cp_blob[offset:offset+size]
        # Despite its name, the retained capture's dyload entry is a
        # variable/controller/event-memory initializer, not evidence that
        # the RF executable is downloaded again on each capture.
        dyload=symbols.get_symbol_by_name('rf_lte_init_dyload')[0]
        dysection=elf.get_section(dyload['st_shndx'])
        dya=dyload['st_value']&~1
        dycode=dysection.data()[dya-dysection['sh_addr']:dya-dysection['sh_addr']+dyload['st_size']]
        dycalls=[]
        for instruction in decoder.disasm(dycode,dya):
            if instruction.mnemonic in ('bl','b.w'):
                target=int(instruction.op_str.lstrip('#'),16)
                names=[s.name for s in symbols.iter_symbols() if s['st_info']['type']=='STT_FUNC' and s['st_value']&~1==target]
                assert len(names)==1
                dycalls.append(dict(address=hex(instruction.address),target=hex(target),symbol=names[0]))
        assert [x['symbol'] for x in dycalls]==['b_idle_init','rf_var_init','b_rfad_init','b_rfad_mem_init']
        dybin=[i for i in decoder.disasm(linear_bytes(0x801d8c70,24),0x801d8c70) if i.mnemonic in ('bl','b.w')]
        assert [i.op_str for i in dybin]==['#0x801db858','#0x802c3ec8','#0x802f0670','#0x801db8e0']
        on = linear_bytes(0x8020306c, 24)
        off = linear_bytes(0x802d3fcc, 24)
        assert on == bytes.fromhex('0449c26a4ff43210c98840ea0110106070470000acd54e80')
        assert off == bytes.fromhex('0349c26a0348c98840ea011010607047acd54e8001802c00')
        # Objects for one concrete TDD and one concrete FDD branch: the
        # literal-pool base is advanced by 0x78 before being passed as r0.
        tdd_base = int.from_bytes(scatter_bytes(0x806710, 4), 'little')
        fdd_base = int.from_bytes(scatter_bytes(0x806b80, 4), 'little')
        assert (tdd_base, fdd_base) == (0x804ee900, 0x804efc50)
        assert int.from_bytes(scatter_bytes(0x8066fc, 4), 'little') == 0x804eda30
        assert int.from_bytes(scatter_bytes(0x80672c, 4), 'little') == 0x804ee42c
        assert int.from_bytes(scatter_bytes(0x806b94, 4), 'little') == 0x804ef2a8
        for address, reg in ((0x806356, 'r7'), (0x8067fa, 'r8')):
            ins = next(decoder.disasm(scatter_bytes(address, 4), address))
            assert ins.mnemonic == 'add.w' and ins.op_str == f'r0, {reg}, #0x78'
        rx_dispatch = list(decoder.disasm(scatter_bytes(0x804ed8, 28), 0x804ed8))
        by_address = {i.address: i for i in rx_dispatch}
        assert (by_address[0x804ed8].mnemonic, by_address[0x804ed8].op_str) == ('ldrh.w', 'r0, [sl, #2]')
        assert (by_address[0x804ede].mnemonic, by_address[0x804ede].op_str) == ('bne', '#0x804e6c')
        assert (by_address[0x804ee2].mnemonic, by_address[0x804ee2].op_str) == ('cmp', 'r0, #1')
        assert (by_address[0x804ee6].mnemonic, by_address[0x804ee6].op_str) == ('beq', '#0x804eee')
        assert by_address[0x804ee8].op_str == '#0x8067ba'
        assert by_address[0x804eee].op_str == '#0x806304'
        # The BIN literal pool supplies relocated global addresses. ELF
        # symbol and DWARF evidence establish corresponding field names.
        pool = int.from_bytes(scatter_bytes(0x80502c, 4), 'little')
        assert pool == 0x804ed5f8
        prior_gate_base = int.from_bytes(scatter_bytes(0x805078, 4), 'little')
        assert prior_gate_base == 0x804ed734
        gate_insn = {i.address: i for i in decoder.disasm(scatter_bytes(0x804e64, 4), 0x804e64)}
        assert (gate_insn[0x804e64].mnemonic, gate_insn[0x804e64].op_str) == ('ldrh', 'r0, [r1, #4]')
        assert (gate_insn[0x804e66].mnemonic, gate_insn[0x804e66].op_str) == ('cbz', 'r0, #0x804ed6')
        # A second RXON dispatch lives in AGC processing. The request can
        # queue pending work instead of calling RXON immediately.
        agc = {i.address:i for i in decoder.disasm(scatter_bytes(0x805250,0x176),0x805250)}
        assert agc[0x8052d4].op_str == '#0x806304'
        assert agc[0x8052da].op_str == '#0x8067ba'
        assert (agc[0x8053a0].mnemonic,agc[0x8053a0].op_str)==('ldrh','r0, [r4, #0xa]')
        assert agc[0x8053a4].op_str == '#0x805376'
        assert agc[0x8053b2].op_str == '#0x8052da'
        # Execute only the gate/dispatch fragments with synthetic globals.
        # Stop before native RXON: no device register or calibration model.
        import sys
        sys.path.insert(0,str(ROOT/'work/host-test-deps'))
        from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
        from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8,UC_ARM_REG_R9,UC_ARM_REG_R10,UC_ARM_REG_LR,UC_ARM_REG_PC
        cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
        cpu.mem_map(0x804000,0x30000);cpu.mem_map(0x804e0000,0x10000)
        cpu.mem_write(0x804000,scatter_bytes(0x804000,scatter[3]))
        reached=[]
        off_calls=[]
        def stop_at_dispatch(machine,address,size,context):
            if address in (0x806c24,0x806ae8):
                # Explicit boundary: skip physical RXOFF implementation.
                off_calls.append(address)
                machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR))
                return
            if address in (0x804e6c,0x806304,0x8067ba,0x805376):
                reached.append(address);machine.emu_stop()
        cpu.hook_add(UC_HOOK_CODE,stop_at_dispatch)
        request_cases=[]
        for gate,event,duplex,target,pending in ((1,0,0,0x804e6c,1),(0,1,0,0x804e6c,0),(0,0,0,0x8067ba,0),(0,0,1,0x806304,0)):
            cpu.mem_write(0x804ed734,bytes(16));cpu.mem_write(0x804ed738,struct.pack('<H',gate))
            cpu.mem_write(0x804ed566,struct.pack('<H',event));cpu.mem_write(0x804ed5d4,struct.pack('<H',duplex))
            for reg,value in ((UC_ARM_REG_R1,0x804ed734),(UC_ARM_REG_R4,0x804ed5f8),(UC_ARM_REG_R7,0x804ed5ac),(UC_ARM_REG_R8,1),(UC_ARM_REG_R10,0x804ed564)):
                cpu.reg_write(reg,value)
            reached.clear();cpu.emu_start(0x804e65,0,count=100)
            assert reached==[target] and int.from_bytes(cpu.mem_read(0x804ed73e,2),'little')==pending
            request_cases.append(dict(gate=gate,event_flag=event,duplex=duplex,target=hex(target),pending=pending))
        agc_cases=[]
        for pending,duplex,target in ((0,0,0x805376),(1,0,0x8067ba),(1,1,0x806304)):
            cpu.mem_write(0x804ed73e,struct.pack('<H',pending));cpu.mem_write(0x804ed5d4,struct.pack('<H',duplex))
            cpu.reg_write(UC_ARM_REG_R4,0x804ed734);cpu.reg_write(UC_ARM_REG_R9,0x804ed5ac)
            reached.clear();cpu.emu_start(0x8053a1,0,count=100)
            assert reached==[target]
            agc_cases.append(dict(pending=pending,duplex=duplex,target=hex(target)))
        # Earlier AGC gates require a queued RXOFF too. Enter both native
        # routes before that check, mocking only RXOFF at its call boundary.
        agc_gate_cases=[]
        for entry in (0x805382,0x8052a4):
            for off_pending in (0,1):
                for pending in (0,1):
                    for duplex in (0,1):
                        cpu.mem_write(0x804ed734,bytes(16))
                        cpu.mem_write(0x804ed73c,struct.pack('<HH',off_pending,pending))
                        cpu.mem_write(0x804ed5d4,struct.pack('<H',duplex))
                        for reg,value in ((UC_ARM_REG_R4,0x804ed734),(UC_ARM_REG_R5,0x804ed5ac),
                                          (UC_ARM_REG_R8,0x804ed5ac),(UC_ARM_REG_R9,0)):
                            cpu.reg_write(reg,value)
                        reached.clear();off_calls.clear()
                        cpu.emu_start(entry|1,0,count=100)
                        expected_target=(0x806304 if duplex else 0x8067ba) if off_pending and pending else 0x805376
                        assert reached==[expected_target]
                        assert off_calls==([0x806ae8 if duplex else 0x806c24] if off_pending else [])
                        assert int.from_bytes(cpu.mem_read(0x804ed73c,2),'little')==0
                        # The pending RXON is consumed only after RXON returns.
                        assert int.from_bytes(cpu.mem_read(0x804ed73e,2),'little')==pending
                        agc_gate_cases.append(dict(entry=hex(entry),rxoff_pending=off_pending,
                            rxon_pending=pending,duplex=duplex,target=hex(expected_target),
                            mocked_rxoff_calls=[hex(x) for x in off_calls]))
        # Execute the real post-RXON cleanup independently, no RXON model.
        cpu.mem_write(0x804ed73e,struct.pack('<H',1))
        cpu.mem_write(0x804ed566,struct.pack('<H',1))
        cpu.reg_write(UC_ARM_REG_R4,0x804ed734);cpu.reg_write(UC_ARM_REG_R5,0)
        cpu.reg_write(UC_ARM_REG_R6,0x804ed564)
        reached.clear();cpu.emu_start(0x8052df,0,count=10)
        assert reached==[0x805376]
        assert bytes(cpu.mem_read(0x804ed73e,2))==bytes(2)
        assert bytes(cpu.mem_read(0x804ed566,2))==bytes(2)
        # Native switch helpers load the object pointer and selector, then
        # issue a 32-bit command store. They do not read RAM2 back. The model
        # proves access width/order only, not physical readback semantics.
        cpu.mem_map(0x80203000,0x1000);cpu.mem_map(0x802d3000,0x1000)
        cpu.mem_map(0x25100000,0x3000)
        cpu.mem_write(0x8020306c,on);cpu.mem_write(0x802d3fcc,off)
        accesses=[]
        def read_access(machine,access,address,size,value,context):
            accesses.append(('read',address,size))
        def write_access(machine,access,address,size,value,context):
            accesses.append(('write',address,size,value))
        cpu.hook_add(UC_HOOK_MEM_READ,read_access);cpu.hook_add(UC_HOOK_MEM_WRITE,write_access)
        helper_cases=[]
        obj=0x804ee978;slot=0x25101340
        for selector in (0,4,6,15):
            for entry,operation in ((0x8020306c,0),(0x802d3fcc,1)):
                cpu.mem_write(obj+44,struct.pack('<I',slot));cpu.mem_write(0x804ed5b2,struct.pack('<H',selector))
                cpu.reg_write(UC_ARM_REG_R0,obj);cpu.reg_write(UC_ARM_REG_R1,0xdeadbeef)
                cpu.reg_write(UC_ARM_REG_LR,0x80400001);accesses.clear()
                cpu.emu_start(entry|1,0x80400000,count=20)
                command=0x2c8000|(selector<<4)|operation
                assert cpu.reg_read(UC_ARM_REG_PC)==0x80400000
                data_reads=[x for x in accesses if x[0]=='read' and not entry<=x[1]<entry+24]
                assert data_reads==[('read',obj+44,4),('read',0x804ed5b2,2)]
                assert [x for x in accesses if x[0]=='write']==[('write',slot,4,command)]
                helper_cases.append(dict(selector=selector,operation=operation,command=hex(command),width=4,slot_readback=False))
        # Event enable/disable are distinct from the RAM2 command store.
        # Execute their actual BIN bodies and keep the static RXON ordering.
        cpu.mem_map(0x80296000,0x2000)
        event_controls=[]
        for entry,enable,length in ((0x80297604,True,10),(0x8029673a,False,10)):
            cpu.mem_write(entry,linear_bytes(entry,length))
            for initial in (0,0x40000000,0x80001234,0xffffffff):
                cpu.mem_write(0x25101000,struct.pack('<I',initial))
                cpu.reg_write(UC_ARM_REG_R0,0x25101000)
                cpu.reg_write(UC_ARM_REG_LR,0x80400001);accesses.clear()
                cpu.emu_start(entry|1,0x80400000,count=10)
                expected=(initial|0x40000000) if enable else (initial&~0x40000000)
                assert cpu.reg_read(UC_ARM_REG_PC)==0x80400000
                assert [x for x in accesses if x[0]=='write']==[('write',0x25101000,4,expected)]
                assert int.from_bytes(cpu.mem_read(0x25101000,4),'little')==expected
                event_controls.append(dict(entry=hex(entry),enable=enable,initial=hex(initial),result=hex(expected)))
        sequences=[]
        for start,size in ((0x806304,0x3f6),(0x8067ba,0x318)):
            calls=[]
            for instruction in decoder.disasm(scatter_bytes(start,size),start):
                if instruction.mnemonic!='blx':continue
                target=int(instruction.op_str.lstrip('#'),16)
                kind={0x81b598:'switch_command_store',0x81b618:'event_bit30_set',0x81b620:'event_bit30_clear'}.get(target)
                if kind:
                    calls.append(dict(address=hex(instruction.address),kind=kind,target=hex(target)))
            assert sum(x['kind']=='switch_command_store' for x in calls)==(3 if start==0x806304 else 2)
            sequences.append(dict(entry=hex(start),calls_in_address_order=calls,
                scope='Address order across conditional branches; not a single executed path or a hardware timeline.'))
        # On the first normal TDD/FDD paths, the enabled event index is
        # config+0x10, whereas the conditional clear uses config+0x0c.
        # They must not be reported as a shared latch on the switch slot.
        for addr,operands in ((0x8063a4,'r1, [r6, #0x10]'),
                              (0x806406,'r3, [r6, #0xc]'),
                              (0x806848,'r1, [r5, #0x10]'),
                              (0x8068aa,'r3, [r5, #0xc]')):
            instruction=next(decoder.disasm(scatter_bytes(addr,4),addr))
            assert instruction.mnemonic=='ldrh' and instruction.op_str==operands
        assert int.from_bytes(scatter_bytes(0x806714,4),'little')==0x25101000
        assert int.from_bytes(scatter_bytes(0x806b88,4),'little')==0x25101000
        assert int.from_bytes(scatter_bytes(0x806b84,4),'little')==0x804eda30
        assert (0x804ee900+0x78+0x84,0x804eda30+0x231c)==(0x804ee9fc,0x804efd4c)
        assert next(decoder.disasm(scatter_bytes(0x806364,4),0x806364)).op_str=='r6, r0, #0x84'
        assert next(decoder.disasm(scatter_bytes(0x8067f2,4),0x8067f2)).op_str=='r3, #0x231c'
        assert symbols.get_symbol_by_name('st_rf_lterx_info')[0]['st_value'] == 0x804d97cc
        assert symbols.get_symbol_by_name('g_lterx_event_flag')[0]['st_value'] == 0x804d973a
        assert symbols.get_symbol_by_name('st_rf_lte_info')[0]['st_value'] == 0x804d9780
        found = False
        for cu in elf.get_dwarf_info().iter_CUs():
            for die in cu.iter_DIEs():
                name = die.attributes.get('DW_AT_name')
                if die.tag != 'DW_TAG_variable' or not name or name.value != b'st_rf_lte_info':
                    continue
                ty = die.get_DIE_from_attribute('DW_AT_type')
                while ty.tag != 'DW_TAG_structure_type':
                    ty = ty.get_DIE_from_attribute('DW_AT_type')
                for member in ty.iter_children():
                    field = member.attributes.get('DW_AT_name')
                    if field and field.value == b'u16_tddfdd_flag':
                        assert member.attributes['DW_AT_data_member_location'].value == [0x23, 0x28]
                        found = True
                        break
                if found:
                    break
            if found:
                break
        assert found
    report = dict(status='passed', device_accessed=False, sites=sites,
                  capture_dyload=dict(elf_entry=hex(dya),bin_entry='0x801d8c70',elf_calls=dycalls,
                      bin_targets=[i.op_str for i in dybin],
                      scope='Static wrapper targets and ELF symbol correspondence only. Does not prove full callee effects, executable image reload, cache synchronization or runtime execution.'),
                  scope='Static calls and ARM-to-Thumb veneers only; no branch condition, runtime event delivery, RFFE transaction or hardware state proved.',
                  event_entry_comparison=comparison,
                  bin_scatter=dict(record_offset='0x2bc4dc',source=hex(scatter[1]),destination=hex(scatter[2]),
                                   length=hex(scatter[3]), mapped_calls=mapped_calls,
                                   scope='CP BIN scatter and static instructions; runtime low-memory bytes and execution not checked.'),
                  bin_helpers=dict(swon='0x8020306c',swoff='0x802d3fcc',selector_base='0x804ed5ac',
                                   selector_offset=6, command_pointer_offset=44,
                                   open_base='0x2c8000',close_base='0x2c8001',
                                   scope='Static BIN helper instructions; command-pointer validity, event execution and bus delivery not observed.'),
                  native_helper_accesses=dict(cases=helper_cases,
                      scope='Native BIN helpers with synthetic RAM: exactly object pointer load, CP selector halfword load and command word store. No RAM2 readback; physical bus delivery/read semantics unproved.'),
                  event_control=dict(native_cases=event_controls,rxon_sequences=sequences,
                      first_normal_path=dict(event_index_enable_offset='0x10',event_index_conditional_clear_offset='0x0c',
                          tdd_configuration='0x804ee9fc',fdd_configuration='0x804efd4c',
                          tdd_event_bank_base='0x25101000',switch_command_pointer_offset='0x2c',
                          scope='Different configuration fields; their runtime index values could coincide. No common switch latch inferred.'),
                      scope='Native event helpers only toggle bit30 of synthetic event RAM. Static call order does not prove trigger timing, bank execution, or RFFE delivery.'),
                  example_event_objects=dict(tdd='0x804ee978',fdd='0x804efcc8',
                                             scope='Two conditional RXON branches only; not proof either was selected at runtime.'),
                  additional_candidate_bases=dict(tdd_base='0x804eda30', tdd_alternate='0x804ee42c',
                                                  fdd_alternate='0x804ef2a8',
                                                  scope='Static literal pools, no claim that a candidate was selected or modified.'),
                  rx_dispatch=dict(entry='0x804c00',gate='[sl+2] must be zero at 0x804ed8; earlier [r1+4] branch also applies',
                                   selector='[r7+0x28] == 1 selects TDD 0x806304; otherwise FDD 0x8067ba',
                                   bin_literal_pool=hex(pool), bin_event_flag='0x804ed566', bin_tddfdd_flag='0x804ed5d4',
                                   prior_gate_address='0x804ed738', prior_gate_required_value=0,
                                   elf_event_flag='g_lterx_event_flag', elf_tddfdd_field='st_rf_lte_info.u16_tddfdd_flag',
                                   scope='Static ELF symbol/DWARF and BIN literal correspondence; flag values at dispatch and runtime execution are not established.'),
                  deferred_rx_dispatch=dict(agc_entry='0x805250',pending_flag='0x804ed73e',
                      request_cases=request_cases,agc_cases=agc_cases,agc_prior_gate_cases=agc_gate_cases,
                      rxoff_pending_flag='0x804ed73c',post_rxon_clear=['0x804ed73e','0x804ed566'],
                      elf_rxon_calls=rxon_calls,elf_agc_callers=agc_callers,
                      scope='Actual BIN gate fragments executed with synthetic globals; stop before RXON. AGC caller and interrupt timing at runtime remain unproved. Zero immediate snapshots do not exclude later RXON.'),
                  dependencies={str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), CP, CP_BIN, OBJDUMP)})
    path = ROOT / 'records/rf/reference-rffe-cp-callers.json'
    path.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(status='passed', call_sites=len(sites), output=str(path.relative_to(ROOT)))))


if __name__ == '__main__':
    main()
