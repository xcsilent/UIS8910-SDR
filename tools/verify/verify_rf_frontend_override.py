"""Run bounded FEM template override and recovery paths as compiled ARM C."""
import argparse
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/host-test-deps'))
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    assert not args.output.exists() and args.output.resolve().is_relative_to(ROOT)
    directory=ROOT/'work/rf-frontend-override-check';directory.mkdir(exist_ok=True)
    harness=directory/'bus.c'
    harness.write_text('#include "rf_bus.h"\n'
        'uint32_t test_read(void*c,uint32_t a,unsigned n){(void)c;(void)a;(void)n;return 0;}\n'
        'void test_write(void*c,uint32_t a,uint32_t v,unsigned n){(void)c;(void)a;(void)v;(void)n;}\n',encoding='utf-8')
    source=ROOT/'firmware/rf_rebuild/rf_frontend_override.c'
    gcc=ROOT/'inputs/repositories/rda8910-csdk-hotelec/prebuilts/win32/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
    cases=[];elfs=[]
    for opt in ('O0','O2'):
        image=directory/(opt+'.elf');elfs.append(image)
        subprocess.run([str(gcc),'-mcpu=cortex-a5','-mthumb','-mfloat-abi=soft','-'+opt,
            '-nostdlib','-ffreestanding','-fno-builtin','-Wall','-Wextra','-Werror',
            '-Wl,--build-id=none','-Wl,-Ttext=0x100000','-Wl,-e,rf_frontend_override_apply',
            '-I'+str(source.parent),str(source),str(harness),'-o',str(image)],check=True)
        for row in (4,6):
            for scenario in ('normal','same_value','busy','bad_row','bad_value','active',
                'bad_signature','bad_pointer','bad_band','bad_source','bad_copy',
                'write_ignored','restore_ignored','restore_conflict','restore_busy','corrupt_state'):
                cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM)
                cpu.mem_map(0x100000,0x10000);cpu.mem_map(0x200000,0x20000)
                with image.open('rb') as f:
                    elf=ELFFile(f)
                    for segment in elf.iter_segments():
                        if segment['p_type']=='PT_LOAD' and segment['p_filesz']:
                            cpu.mem_write(segment['p_vaddr'],segment.data())
                    sy={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
                address=0x500097f0 if row==4 else 0x50009810
                original=0xd0005 if row==4 else 0xd0002
                nv=0x804f42b8
                memory={0x500010e8:0x0120506f,0x50007e18:0x96b0,
                    nv+0x20+2*row:5 if row==4 else 8,
                    nv+0x310+16*row:original,address:original}
                for case,key in (('bad_signature',0x500010e8),('bad_pointer',0x50007e18),
                    ('bad_band',nv+0x20+2*row),('bad_source',nv+0x310+16*row),('bad_copy',address)):
                    if scenario==case:memory[key]^=1
                io=[];phase=['apply']
                def callback(c,pc,size,context):
                    if pc==(sy['test_read']&~1):
                        a=c.reg_read(UC_ARM_REG_R1);width=c.reg_read(UC_ARM_REG_R2)
                        assert a in memory and width in (2,4),(hex(a),width)
                        io.append(('read',a,width,memory[a]))
                        c.reg_write(UC_ARM_REG_R0,memory[a]);c.reg_write(UC_ARM_REG_PC,c.reg_read(UC_ARM_REG_LR))
                    elif pc==(sy['test_write']&~1):
                        a=c.reg_read(UC_ARM_REG_R1);v=c.reg_read(UC_ARM_REG_R2);width=c.reg_read(UC_ARM_REG_R3)
                        assert a==address and width==1 and v in (2,5)
                        io.append(('write',a,width,v))
                        ignored=scenario=='write_ignored' or (scenario=='restore_ignored' and phase[0]=='restore')
                        if not ignored:memory[a]=(memory[a]&~255)|v
                        c.reg_write(UC_ARM_REG_PC,c.reg_read(UC_ARM_REG_LR))
                cpu.hook_add(UC_HOOK_CODE,callback)
                bus,state=0x200000,0x200100
                cpu.mem_write(bus,struct.pack('<3I',0,sy['test_read'],sy['test_write']))
                cpu.mem_write(state,struct.pack('<4I',0,0,0,1 if scenario=='active' else 0))
                def call(name,params):
                    cpu.reg_write(UC_ARM_REG_SP,0x20f000)
                    for r,v in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),params[:4]):cpu.reg_write(r,v)
                    if len(params)>4:cpu.mem_write(0x20f000,struct.pack('<I',params[4]))
                    cpu.reg_write(UC_ARM_REG_LR,0x70000000)
                    cpu.emu_start(sy[name]|1,0x70000000,count=10000)
                    assert cpu.reg_read(UC_ARM_REG_PC)==0x70000000
                    v=cpu.reg_read(UC_ARM_REG_R0);return v-(1<<32) if v>>31 else v
                value=(original&255) if scenario=='same_value' else (2 if row==4 else 5)
                result=call('rf_frontend_override_apply',[bus,state,7 if scenario=='bad_row' else row,
                    9 if scenario=='bad_value' else value,0 if scenario=='busy' else 1])
                invalid=scenario in ('busy','bad_row','bad_value','active')
                bad_context=scenario.startswith('bad_') and not invalid
                assert result==(-1 if invalid else -2 if bad_context else -3 if scenario=='write_ignored' else 0),(scenario,result)
                if invalid or bad_context:
                    assert not any(r[0]=='write' for r in io)
                    if invalid:assert not io
                else:
                    assert struct.unpack('<4I',cpu.mem_read(state,16))[3]==1
                    if scenario=='restore_conflict':memory[address]^=0x100
                    if scenario=='corrupt_state':cpu.mem_write(state,struct.pack('<I',0x50000000))
                    phase[0]='restore';count=len(io)
                    restored=call('rf_frontend_override_restore',[bus,state,0 if scenario=='restore_busy' else 1])
                    expected=-4 if scenario=='restore_conflict' else -3 if scenario=='restore_ignored' else -1 if scenario in ('restore_busy','corrupt_state') else 0
                    assert restored==expected,(scenario,restored)
                    assert struct.unpack('<4I',cpu.mem_read(state,16))[3]==(1 if expected else 0)
                    if not expected:assert memory[address]==original
                    if scenario in ('restore_busy','corrupt_state'):assert len(io)==count
                    if scenario=='restore_conflict':assert not any(r[0]=='write' for r in io[count:])
                cases.append(dict(optimization=opt,row=row,scenario=scenario,result=result))
    deps=[Path(__file__),source,source.with_suffix('.h'),source.parent/'rf_bus.h',harness,gcc]+elfs
    report=dict(status='passed',device_accessed=False,hardware_tested=False,cases=cases,
        enabled_in_current_firmware=False,
        scope='Compiled ARM O0/O2 control flow with synthetic ordered bus callbacks and injected rejection/readback/recovery failures. No RF/cache/ownership/ACK or integration proof.',
        dependencies={x.relative_to(ROOT).as_posix():hashlib.sha256(x.read_bytes()).hexdigest() for x in deps})
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status='passed',cases=len(cases),device_accessed=False)))


if __name__=='__main__':main()
