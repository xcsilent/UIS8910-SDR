"""Locate the vendor RXCAPT table producer in retained CP bytes."""
import hashlib,json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/host-test-deps'))
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
BASE=ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin'
axf=BASE/'cp.axf';cp=BASE/'cp.bin'
with axf.open('rb') as f:
    elf=ELFFile(f);sym=elf.get_section_by_name('.symtab')
    function=next(s for s in sym.iter_symbols() if s.name=='algo_lte_rxcapt_sf_cal_capt_rx')
    section=elf.get_section(function['st_shndx']);address=function['st_value']&~1
    code=section.data()[address-section['sh_addr']:address-section['sh_addr']+38]
blob=cp.read_bytes();positions=[];start=0
while True:
    i=blob.find(code,start)
    if i<0:break
    positions.append(i);start=i+1
assert len(positions)==1
# Thumb addw r2,r2,#1999 followed by strd r3,r2,[r0,#8].
assert bytes.fromhex('02f2cf72c0e90232') in code
copier,source,destination,length=struct.unpack_from('<4I',blob,0x2bc4dc)
assert (copier,source,destination,length)==(0x8025b8e8,0x804750bc,0x804000,0x29724)
entry=0x81dac4
assert source-0x801ab000+entry-destination==positions[0]
uc=Uc(UC_ARCH_ARM,UC_MODE_ARM)
uc.mem_map(0x800000,0x30000)
uc.mem_write(destination,blob[source-0x801ab000:source-0x801ab000+length])
uc.mem_map(0x80400000,0x100000)
uc.mem_map(0x70000000,0x1000)
rows=[]
for initial in (0,1999,2047,0x12345fff):
    table=0x804fe900
    uc.mem_write(table,struct.pack('<4I',0,0,0,initial))
    for reg,value in ((UC_ARM_REG_R0,0),(UC_ARM_REG_SP,0x804ff000),(UC_ARM_REG_LR,0x70000000)):
        uc.reg_write(reg,value)
    uc.emu_start(entry|1,0x70000000,count=100)
    assert uc.reg_read(UC_ARM_REG_PC)==0x70000000
    words=struct.unpack('<4I',uc.mem_read(table,16))
    assert words[0]==3 and words[2]==1 and words[3]==(initial&~2047)|1999
    rows.append({'initial':initial,'end':words[3]})
inputs=[Path(__file__).resolve(),axf,cp]
result={'status':'passed','device_accessed':False,'hardware_tested':False,
 'symbol':'algo_lte_rxcapt_sf_cal_capt_rx','elf_address':hex(address),'cp_bin_unique_offset':hex(positions[0]),
 'code_hex':code.hex(),'observed_behavior':'preserves upper bits of previous end field, replaces low 11 bits with 1999; a value of 2047 cannot result',
 'scatter_record_offset':'0x2bc4dc','runtime_entry':hex(entry),'emulated_table_cases':rows,
 'limitation':'Retained CP binary and scatter metadata determine runtime mapping; emulated function does not establish physical hardware behavior.',
 'dependencies':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}}
output=ROOT/'records/rf/reference-rf-dual-v17-vendor-capture-end.json'
output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
