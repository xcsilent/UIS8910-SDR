"""ARM-compiled standard/experimental PRE profiles and build contract guards."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/host-test-deps'))
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_LR,UC_ARM_REG_PC


def main():
    build=ROOT/'work/rx-pre-profile-test';build.mkdir(exist_ok=True)
    source=build/'profile.c'
    source.write_text('#include "rxcapt_rx_pre_profile.h"\nuint32_t profile(uint32_t bw){return rxcapt_rx_pre_profile(bw);}\nuint32_t profile_switch(uint32_t bw,uint32_t sel){return rxcapt_rx_pre_switch_profile(bw,sel);}\n')
    gcc=ROOT/'inputs/repositories/rda8910-csdk-hotelec/prebuilts/win32/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
    rows=[]
    for selector in (None,6,7):
        elfpath=build/('standard.elf' if selector is None else f'selector{selector}.elf')
        cmd=[str(gcc),'-mcpu=cortex-a5','-mthumb','-O2','-ffreestanding','-nostdlib',
             '-I'+str(ROOT/'firmware/capture'),'-Wl,--build-id=none','-Wl,-Ttext=0x100000','-Wl,-e,profile']
        if selector is not None:cmd.append('-DRXCAPT_EXPERIMENTAL_BW5_PRE_SELECTOR='+str(selector))
        subprocess.run(cmd+[str(source),'-o',str(elfpath)],check=True,capture_output=True)
        cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);cpu.mem_map(0x100000,0x10000);cpu.mem_map(0x200000,0x1000)
        with elfpath.open('rb') as stream:
            elf=ELFFile(stream)
            symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
            entry=symbols['profile'];switch_entry=symbols['profile_switch']
            for segment in elf.iter_segments():
                if segment['p_type']=='PT_LOAD' and segment['p_filesz'] and 0x100000<=segment['p_vaddr']<0x110000:
                    cpu.mem_write(segment['p_vaddr'],segment.data())
        for bw in range(6):
            cpu.reg_write(UC_ARM_REG_R0,bw);cpu.reg_write(UC_ARM_REG_LR,0x200001)
            cpu.emu_start(entry|1,0x200000,count=100)
            expected=((selector if bw==5 and selector is not None else bw)<<8)|8
            actual=cpu.reg_read(UC_ARM_REG_R0)
            assert cpu.reg_read(UC_ARM_REG_PC)==0x200000 and actual==expected
            rows.append(dict(experimental_selector=selector,rf_mode=bw,pre_cfg=hex(actual)))
        for bw in range(6):
            for selected in (0,4,5,6,7,8):
                cpu.reg_write(UC_ARM_REG_R0,bw);cpu.reg_write(UC_ARM_REG_R1,selected);cpu.reg_write(UC_ARM_REG_LR,0x200001)
                cpu.emu_start(switch_entry|1,0x200000,count=100)
                expected=(((selected if bw==5 and 5<=selected<=7 else bw)<<8)|8)
                assert cpu.reg_read(UC_ARM_REG_PC)==0x200000 and cpu.reg_read(UC_ARM_REG_R0)==expected
    rejected=[]
    for selector in (-1,0,5,8,65535):
        result=subprocess.run([str(gcc),'-I'+str(ROOT/'firmware/capture'),
            '-DRXCAPT_EXPERIMENTAL_BW5_PRE_SELECTOR='+str(selector),'-c',str(source),'-o',str(build/'invalid.o')],capture_output=True)
        assert result.returncode and b'experimental BW5 PRE selector' in result.stderr
        rejected.append(selector)
    # CLI rejection is exercised before reading/building any artifacts.
    result=subprocess.run([sys.executable,'-B',str(ROOT/'tools/build_capture_bridge.py'),
        '--experimental-bw5-pre-selector','6'],capture_output=True)
    assert result.returncode and b'explicit generation' in result.stderr
    paths=[Path(__file__),ROOT/'firmware/capture/rxcapt_rx_pre_profile.h',ROOT/'tools/build_capture_bridge.py',ROOT/'tools/build_receiver.py']
    report=dict(status='passed',recorded_at=datetime.now().astimezone().isoformat(),device_accessed=False,
        rows=rows,rejected_compile_values=rejected,unscoped_builder_rejected=True,
        scope='Compiled ARM helper execution, invalid macro rejection and builder preconditions; no RF/MMIO/DMA hardware proof.',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (ROOT/'records/usb/bandwidth-profile-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(status='passed',ARM_cases=len(rows),rejected_compile_values=rejected)))


if __name__=='__main__':main()
