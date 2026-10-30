"""Run retained CP capture update instructions with emulated MMIO."""
import hashlib,json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/host-test-deps'))
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC

def main():
    cp=ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin/cp.bin'
    blob=cp.read_bytes()
    copier,source,dest,length=struct.unpack_from('<4I',blob,0x2bc4dc)
    assert (copier,source,dest,length)==(0x8025b8e8,0x804750bc,0x804000,0x29724)
    u=Uc(UC_ARCH_ARM,UC_MODE_ARM)
    u.mem_map(0x800000,0x30000);u.mem_map(0x80400000,0x100000);u.mem_map(0x27000000,0x1000)
    u.mem_map(0x70000000,0x1000)
    u.mem_write(dest,blob[source-0x801ab000:source-0x801ab000+length])
    u.mem_write(0x8265d0,bytes.fromhex('1eff2fe1'))  # ARM bx lr; IRQ mask is stubbed
    results=[]
    for end in (1999,2047):
        u.mem_write(0x804fe900,struct.pack('<4I',3,0,1,end))
        u.mem_write(0x27000000,bytes(0x28))
        for reg,val in ((UC_ARM_REG_R0,0),(UC_ARM_REG_SP,0x804ff000),(UC_ARM_REG_LR,0x70000000)):
            u.reg_write(reg,val)
        u.emu_start(0x81daeb,0x81db12,count=1000)
        assert u.reg_read(UC_ARM_REG_PC)==0x81db12
        actual=struct.unpack('<I',u.mem_read(0x27000024,4))[0]
        assert actual==end
        results.append({'table_end':end,'rxcapt_end_register':actual})
    inputs=[Path(__file__).resolve(),cp]
    report={'status':'passed','device_accessed':False,'hardware_tested':False,'cases':results,
            'scope':'actual scatter-loaded vendor update instruction writes 0x27000024; interrupt helper stubbed, MMIO simulated. Not a physical DMA or bandwidth guarantee.',
            'dependencies':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}}
    (ROOT/'records/rf/reference-rf-dual-v17-vendor-capture-update.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
