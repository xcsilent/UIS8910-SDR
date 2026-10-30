"""Compare Python runtime frontend decoder with actual compiled C on ARM."""
import hashlib,json,struct,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'work/host-test-deps'))
from sdr.rf_frontend import decode_row,MIPI,GPO
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
def main():
    report_path=ROOT/'records/rf/runtime-frontend-current.json';report=json.loads(report_path.read_text());assert report['status']=='passed'
    nvpath=ROOT/report['artifacts'][0]['path'];nv=nvpath.read_bytes();assert hashlib.sha256(nv).hexdigest()==report['artifacts'][0]['sha256']
    build=ROOT/'work/rf-frontend-check';build.mkdir(exist_ok=True)
    source=ROOT/'firmware/rf_rebuild/rf_frontend_nv.c';header=source.with_suffix('.h')
    gcc=ROOT/'inputs/repositories/rda8910-csdk-hotelec/prebuilts/win32/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
    cases=0;elfs=[]
    for optimization in ('O0','O2'):
        path=build/(optimization+'.elf');elfs.append(path)
        subprocess.run([str(gcc),'-mcpu=cortex-a5','-mthumb','-mfloat-abi=soft','-'+optimization,'-nostdlib','-ffreestanding','-fno-builtin',
            '-Wl,--build-id=none','-Wl,-Ttext=0x100000','-Wl,-e,uis8910_read_rx_frontend_nv',str(source),'-o',str(path)],check=True)
        cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);cpu.mem_map(0x100000,0x10000);cpu.mem_map(0x200000,0x20000)
        with path.open('rb') as stream:
            elf=ELFFile(stream)
            for segment in elf.iter_segments():
                if segment['p_type']=='PT_LOAD':cpu.mem_write(segment['p_vaddr'],segment.data())
            entry=elf.get_section_by_name('.symtab').get_symbol_by_name('uis8910_read_rx_frontend_nv')[0]['st_value']
        def call(bytes_,row,antenna,ptr=0x200000,out=0x210000):
            cpu.mem_write(0x210000,b'\xa5'*96);cpu.reg_write(UC_ARM_REG_SP,0x20f000);cpu.mem_write(0x20f000,struct.pack('<I',out))
            for reg,value in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),(ptr,bytes_,row,antenna)):cpu.reg_write(reg,value)
            cpu.reg_write(UC_ARM_REG_LR,0x70000000);cpu.emu_start(entry|1,0x70000000,count=100000)
            assert cpu.reg_read(UC_ARM_REG_PC)==0x70000000
            return cpu.reg_read(UC_ARM_REG_R0),bytes(cpu.mem_read(0x210000,96))
        for fixture in (nv,bytes((i*37+i//13)&255 for i in range(16384))):
            cpu.mem_write(0x200000,fixture)
            for row in range(24):
                for antenna in range(4):
                    d=decode_row(fixture,row,antenna);error,actual=call(len(fixture),row,antenna);assert not error
                    expected=bytearray()
                    for name in MIPI:
                        for word in d['mipi'][name]:expected+=bytes(word[k] for k in ('reg_value','reg_addr','slave_id','reserved'))
                    for name in list(GPO)+['antenna']:expected+=struct.pack('<2H',d['gpo'][name]['mask'],d['gpo'][name]['value'])
                    expected+=struct.pack('<HHI',d['mdll_enable'],d['mdll_table_value'],d['gpo_open_command'])
                    assert actual==bytes(expected),(optimization,row,antenna);cases+=1
        for args in ((16383,0,0),(16384,24,0),(16384,0,4),(16384,0,0,0),(16384,0,0,0x200000,0)):
            error,data=call(*args);assert error==0xffffffff and data==b'\xa5'*96
    malformed=0
    for args in ((nv[:-1],0,0),(nv,24,0),(nv,0,4)):
        try:decode_row(*args)
        except ValueError:malformed+=1
        else:raise AssertionError('invalid Python decode accepted')
    deps=[Path(__file__),source,header,nvpath,report_path,ROOT/'tools/sdr/rf_frontend.py']+elfs
    output=dict(status='passed',hardware_tested=False,device_accessed=False,compiled_C_Python_cases=cases,
        rejected_C_cases=10,rejected_Python_cases=malformed,
        scope='actual ARM C parser O0/O2 against Python on current retained runtime NV and synthetic byte pattern,24rows x4antennas; no RF bus commands, physical path or reception proof',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in deps})
    dest=ROOT/'records/rf/runtime-frontend-verification.json';dest.write_text(json.dumps(output,indent=2)+'\n');print(json.dumps(output,indent=2))
if __name__=='__main__':main()
