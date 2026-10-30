"""Exercise linked CP RXCAPT DMA rearm descriptors without accessing hardware."""
import argparse, hashlib, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/host-test-deps'))
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--directory',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    build=json.loads((args.directory/'build.json').read_text(encoding='utf-8'))
    slot_bytes=build.get('slot_bytes',8000)
    image=ROOT/build['resident']['path']
    assert hashlib.sha256(image.read_bytes()).hexdigest()==build['resident']['sha256']
    elf_path=args.directory/'resident.elf'
    uc=Uc(UC_ARCH_ARM,UC_MODE_ARM)
    uc.mem_map(0x80000000,0x1000000)
    uc.mem_map(0x22000000,0x10000)
    uc.mem_map(0x70000000,0x1000)
    with elf_path.open('rb') as stream:
        elf=ELFFile(stream)
        symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        for segment in elf.iter_segments():
            if segment['p_type']=='PT_LOAD' and segment['p_filesz']:
                uc.mem_write(segment['p_vaddr'],segment.data())
    def put(address,*values):uc.mem_write(address,struct.pack('<'+'I'*len(values),*values))
    def words(address,n):return struct.unpack('<'+'I'*n,uc.mem_read(address,4*n))
    # Stub only the vendor DMA-start call; its arguments and descriptor contents
    # are checked at entry. Actual DMA and its timing remain outside the test.
    uc.mem_write(0x802fd0a4,b'\x70\x47')  # Thumb bx lr
    calls=[]
    def hook(machine,address,size,context):
        if address==0x70000000:machine.emu_stop()
        if address==0x802fd0a4:
            calls.append((machine.reg_read(UC_ARM_REG_R0),machine.reg_read(UC_ARM_REG_R1),
                          machine.reg_read(UC_ARM_REG_R2)))
    uc.hook_add(UC_HOOK_CODE,hook)
    put(0x80468a48+7*4,0x22000100)
    put(0x22000100+4*4,0)
    put(0x22000100+6*4,0x00200000)
    def invoke(kind,slot):
        for reg,value in ((UC_ARM_REG_R0,7),(UC_ARM_REG_R1,kind),(UC_ARM_REG_R2,slot),
                          (UC_ARM_REG_SP,0x80eff000),(UC_ARM_REG_LR,0x70000000)):
            uc.reg_write(reg,value)
        uc.emu_start(symbols['rxcapt_ring_poll_rearm']|1,0x70000000,count=10000)
        assert uc.reg_read(UC_ARM_REG_PC)==0x70000000
        return uc.reg_read(UC_ARM_REG_R0)
    for slot in range(7):
        assert invoke(0,slot)==1
        address=0x80960000+slot*slot_bytes
        assert words(0x80474c50,2)==(address,slot_bytes)
        assert words(0x80476660+12,3)==(address,slot_bytes,slot_bytes)
        assert calls[-1]==(2,7,0x80476660)
    assert invoke(0,7)==0 and len(calls)==7
    for slot in (0,6):
        assert invoke(1,slot)==1
        address=0x8096ff00+slot*24
        assert words(0x80474c50+8,2)==(address,24)
        assert words(0x8047668c+12,3)==(address,24,24)
        assert calls[-1]==(2,7,0x8047668c)
    assert invoke(2,0)==0 and len(calls)==9
    paths=[Path(__file__).resolve(),elf_path.resolve(),image.resolve(),(args.directory/'build.json').resolve()]
    report={'status':'passed','device_accessed':False,'hardware_tested':False,'slot_bytes':slot_bytes,
            'scope':'actual linked ARM rearm function, all seven DATA descriptors and HEAD endpoints; vendor DMA-start stubbed, no physical DMA/cache/USB proof',
            'tests':['seven DATA addresses, lengths, globals and DMA call arguments','out-of-range slot rejected','HEAD slots 0 and 6 remain 24 bytes','invalid kind rejected'],
            'dependencies':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
