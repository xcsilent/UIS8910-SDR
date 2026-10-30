"""Execute native CP bandwidth/preprocessor slices; no hardware or firmware changes."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/host-test-deps'))
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R4,UC_ARM_REG_R6,UC_ARM_REG_R7


def main():
    sdk=ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin'
    cp,axf=sdk/'cp.bin',sdk/'cp.axf'
    blob=cp.read_bytes();base=0x801ab000
    slices=[]
    with axf.open('rb') as f:
        elf=ELFFile(f);symbols={s.name:s for s in elf.get_section_by_name('.symtab').iter_symbols()}
        for name,start,end in [('rf_lte_rx_data_req',0x16c,0x172),
                               ('algo_lte_txrx_rx_sf_compara_cal',0x40,0x56),
                               ('algo_lte_txrx_rx_sync_sf_cal',0x7a,0x8a)]:
            s=symbols[name];section=elf.get_section(s['st_shndx']);at=(s['st_value']&~1)-section['sh_addr']
            code=section.data()[at+start:at+end]
            assert blob.count(code)==1,(name,blob.count(code))
            slices.append(dict(name=name,elf_slice=hex((s['st_value']&~1)+start),native_file_offset=hex(blob.find(code)),code_hex=code.hex()))
    cases=[]
    for selected in (0,1,2,3,4,5,6,7):
        for previous in (8,0x12,0xdeadbeef):
            cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM)
            cpu.mem_map(0x80000000,0x1000000);cpu.mem_write(base,blob)
            cpu.mem_map(0x25000000,0x1000)
            context=0x80900000;out=0x80901000
            put=lambda a,v:cpu.mem_write(a,struct.pack('<I',v))
            get=lambda a:struct.unpack('<I',cpu.mem_read(a,4))[0]
            def execute(row):
                at=base+int(row['native_file_offset'],16)
                cpu.emu_start(at|1,at+len(bytes.fromhex(row['code_hex'])),count=30)
            cpu.mem_write(context+0x24,struct.pack('<H',selected))
            cpu.reg_write(UC_ARM_REG_R7,context);cpu.reg_write(UC_ARM_REG_R6,out)
            execute(slices[0]);packed=get(out+8);assert packed==selected<<8
            # Model the explicit handoff to the cell context, not whole scheduling.
            image=packed|0x80|0x40|0x123000|0x12
            put(context+0x8c,image);put(0x25000038,previous)
            cpu.reg_write(UC_ARM_REG_R1,context);cpu.reg_write(UC_ARM_REG_R4,out)
            execute(slices[1]);normal=get(out+0x1c)
            assert normal==((image&~0x40)&~31)|(previous&31)
            cpu.reg_write(UC_ARM_REG_R7,context);cpu.reg_write(UC_ARM_REG_R4,out)
            execute(slices[2]);sync=get(out+0x1c)
            assert sync==((image&~31)|7)&~0x40
            cases.append(dict(selected_bandwidth=selected,previous_pre_cfg=hex(previous),
                              request_pre_cfg=hex(packed),common_pre_cfg=hex(normal),sync_initial_pre_cfg=hex(sync)))
    paths=[Path(__file__),cp,axf,ROOT/'firmware/rf_rebuild/rfad_raw_capture.c']
    report=dict(status='passed',recorded_at=datetime.now().astimezone().isoformat(),device_accessed=False,hardware_tested=False,
        slices=slices,cases=cases,
        conclusion='Native request packs selected bandwidth<<8. Common/sync preparation clears FIR_EN, preserves other supplied preprocessor fields and chooses BITSEL separately. These slices accept bit patterns6/7 but do not establish meaningful hardware bandwidth or RF mode support.',
        scope='Unique actual CP BIN instruction slices matched to ELF; synthetic context handoff between slices, not end-to-end execution or physical enable/clock proof.',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    output=ROOT/'records/usb/bandwidth-cp-preprocessor-verification.json'
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(status='passed',cases=len(cases),slices=slices),indent=2))


if __name__=='__main__':main()
