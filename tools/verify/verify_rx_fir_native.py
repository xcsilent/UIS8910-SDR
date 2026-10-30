"""Execute actual CP BIN RX FIR initializer and table copy, offline.

Only the diagnostic logger is bypassed. Native EESF selection and memcpy run.
This proves an initialization operation, not sample rate or filter response.
"""
import hashlib,json,re,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/host-test-deps'))
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
from elftools.elf.elffile import ELFFile
SDK=ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin'
BASE=0x801ab000
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    cp=SDK/'cp.bin';axf=SDK/'cp.axf';blob=cp.read_bytes()
    expected=json.loads((ROOT/'records/usb/rf-channel-inventory.json').read_text())['cp_sha256']
    assert sha(cp)==expected
    # Native scatter-load record: copier, source, execution destination, bytes.
    record=0x2bc4dc
    copier,source,destination,length=struct.unpack_from('<4I',blob,record)
    assert (copier,source,destination,length)==(0x8025b8e8,0x804750bc,0x804000,0x29724)
    entry=0x80abc3;offset=source-BASE+(entry&~1)-destination
    code=blob[offset:offset+28]
    assert code.hex()=='10b510f05cec08b1174900e0174940f25412bde810401548f9f7d3bb'
    def ram_word(address):return struct.unpack_from('<I',blob,source-BASE+address-destination)[0]
    eesf,normal,target=(ram_word(a) for a in (0x80ac28,0x80ac2c,0x80ac30))
    assert (eesf,normal,target)==(0x8043a104,0x8043a258,0x25017000)
    assert ram_word(0x81b484)==0x801fd00d
    assert struct.unpack_from('<I',blob,0x801fd030-BASE)[0]==0x804f42b8
    binding=ROOT/'firmware/capture/generated/rxcapt_finite_binding.h'
    assert int(re.search(r'RXCAPT_RX_FIR_INIT_ENTRY (0x[0-9a-f]+)u',binding.read_text())[1],16)==entry
    with axf.open('rb') as f:
        elf=ELFFile(f);symbols={s.name:s for s in elf.get_section_by_name('.symtab').iter_symbols()}
        elf_entry=symbols['algo_lte_hw_txrx_rx_fir_init']['st_value']
        tables=[]
        for name,address in [('C_U16_RX_FIR_COEFFICIENT_TAB_EESF',eesf),('C_U16_RX_FIR_COEFFICIENT_TAB',normal)]:
            sym=symbols[name];section=elf.get_section(sym['st_shndx']);at=sym['st_value']-section['sh_addr']
            data=section.data()[at:at+sym['st_size']]
            assert len(data)==340 and data==blob[address-BASE:address-BASE+340]
            tables.append(dict(name=name,elf_address=hex(sym['st_value']),cp_address=hex(address),bytes=340,
                               sha256=hashlib.sha256(data).hexdigest()))
    cases=[]
    for flag in (0,1):
        for bw in range(6):
            machine=Uc(UC_ARCH_ARM,UC_MODE_ARM)
            machine.mem_map(0x80000000,0x1000000);machine.mem_write(BASE,blob)
            machine.mem_map(0x800000,0x40000);machine.mem_write(destination,blob[source-BASE:source-BASE+length])
            machine.mem_map(target,0x1000);machine.mem_map(0x70000000,0x1000)
            machine.mem_write(0x804f42b8+0x176,struct.pack('<H',flag<<14))
            machine.mem_write(0x804ed5ac+0x24,struct.pack('<H',bw))
            machine.mem_write(0x804ed5f8+0x1c,struct.pack('<H',bw))
            machine.reg_write(UC_ARM_REG_SP,0x8097f000);machine.reg_write(UC_ARM_REG_LR,0x70000001)
            observed=[];finished=[]
            def hook(uc,address,size,data):
                if address==0x802e9194: # diagnostic logging veneer, no RF side effect
                    uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
                elif address==0x804384:
                    observed.append([uc.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2)])
                elif address==0x70000000:
                    finished.append(True);uc.emu_stop()
            machine.hook_add(UC_HOOK_CODE,hook)
            machine.emu_start(entry,0,count=20000)
            selected=eesf if flag else normal
            assert finished and observed==[[target,selected,340]],(flag,bw,observed)
            assert bytes(machine.mem_read(target,340))==blob[selected-BASE:selected-BASE+340]
            cases.append(dict(eesf_flag=flag,bandwidth_index=bw,copy_source=hex(selected),copy_bytes=340))
    deps=[Path(__file__),cp,axf,binding,ROOT/'records/usb/rf-channel-inventory.json']
    report=dict(status='passed',device_accessed=False,hardware_tested=False,
        scope='actual CP BIN scatter-loaded initializer, native flag getter and memcpy in ARM emulator; diagnostic logger skipped, MMIO modeled as memory',
        native_entry=hex(entry),sdk_elf_entry=hex(elf_entry),native_file_offset=hex(offset),native_code_hex=code.hex(),
        scatter_record=dict(file_offset=hex(record),source=hex(source),destination=hex(destination),bytes=length),
        destination=hex(target),coefficient_bytes=340,coefficient_halfwords=170,
        selector='RF NV base0x804f42b8 halfword+0x176 bit14 (EESF flag); no bandwidth argument in initializer',
        tables=tables,cases=cases,
        conclusion='This initializer loads one of two complete coefficient images. BW0..5 context changes do not change this copy. Bandwidth-dependent bank selection/decimation must be traced separately and remains unresolved.',
        dependencies={p.relative_to(ROOT).as_posix():sha(p) for p in deps})
    (ROOT/'records/usb/rx-fir-native-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
