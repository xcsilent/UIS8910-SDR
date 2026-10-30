"""PAC-matched native cache helpers and UDC cache-policy argument checks.

CP15 operations are recorded, not emulated as physical cache effects. No
cycle timing, device access, DMA execution or permission to omit cache ops.
"""
import hashlib,json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/usb'))
sys.path.insert(0,str(ROOT/'work/host-test-deps'))
from inspect_udc import pac_ap
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    state=json.loads((ROOT/'docs/project-state.json').read_text(encoding='utf-8'))
    pac=ROOT/state['installed_firmware']['pac'];assert sha(pac)==state['installed_firmware']['sha256']
    ap=pac_ap(pac);load=struct.unpack_from('>I',ap,16)[0];payload=ap[64:]
    sdk=ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/CSDK_RDA8910.elf'
    wanted=('osiDCacheInvalidate','osiDCacheClean','prvDwcEpQueue','prvEpQueueLocked','prvScheduleEpLocked.part.15')
    functions={};dis=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    with sdk.open('rb') as stream:
        elf=ELFFile(stream)
        for s in elf.get_section_by_name('.symtab').iter_symbols():
            if s.name not in wanted:continue
            address=s['st_value']&~1;section=elf.get_section(s['st_shndx']);size=s['st_size']
            code=section.data()[address-section['sh_addr']:address-section['sh_addr']+size]
            assert payload[address-load:address-load+size]==code,s.name
            functions[s.name]=dict(address=hex(address),bytes=size,sha256=hashlib.sha256(code).hexdigest(),
                code=code,disassembly=[dict(address=hex(i.address),mnemonic=i.mnemonic,operands=i.op_str) for i in dis.disasm(code,address)])
    assert set(functions)==set(wanted)
    def cpu_for(name):
        f=functions[name];cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);cpu.mem_map(0x60000000,0x200000)
        cpu.mem_write(int(f['address'],16),f['code']);cpu.mem_map(0x80000000,0x20000)
        cpu.reg_write(UC_ARM_REG_SP,0x8001f000);cpu.reg_write(UC_ARM_REG_LR,0x70000001)
        return cpu,int(f['address'],16)
    cases=[]
    for name in ('osiDCacheInvalidate','osiDCacheClean'):
        f=functions[name];instructions={int(i['address'],16):i for i in f['disassembly']}
        for address,bytes_ in ((0x80960000,8000),(0x80961f40,8000),(0x8096fa40,32),(0x8096fa40,128),(0x80960001,32)):
            cpu,pc=cpu_for(name);cpu.reg_write(UC_ARM_REG_R0,address);cpu.reg_write(UC_ARM_REG_R1,bytes_)
            operations=[];barriers=[]
            for steps in range(5000):
                if pc==0x70000000:break
                instruction=instructions[pc];op=instruction['mnemonic']
                if op in ('mcr','dsb','dmb'):
                    if op=='mcr':
                        assert 'p15' in instruction['operands'] and 'c7' in instruction['operands']
                        operations.append(cpu.reg_read(UC_ARM_REG_R0))
                    else:barriers.append(op)
                    pc+=4;cpu.reg_write(UC_ARM_REG_PC,pc|1)
                else:
                    cpu.emu_start(pc|1,0x70000000,count=1);pc=cpu.reg_read(UC_ARM_REG_PC)
            else:raise AssertionError('cache helper instruction budget exceeded')
            expected=list(range(address&~31,(address+bytes_+31)&~31,32))
            assert operations==expected and barriers[-1]=='dsb'
            cases.append(dict(function=name,address=hex(address),bytes=bytes_,line_operations=len(operations),
                instruction_steps=steps,barriers=barriers,first_line=hex(operations[0]),last_line=hex(operations[-1])))
    # Execute the scheduling slice that removes a queued request and forms
    # DMA-start arguments. The payload address is deliberately NOT mapped.
    # This does not execute the later controller/register/DMA code.
    policies=[]
    for uncached in (0,1):
        cpu,start=cpu_for('prvScheduleEpLocked.part.15')
        endpoint,request,controller=0x80001000,0x80002000,0x80003000
        cpu.reg_write(UC_ARM_REG_R4,endpoint);cpu.reg_write(UC_ARM_REG_R5,request);cpu.reg_write(UC_ARM_REG_R6,controller)
        cpu.mem_write(endpoint+12,struct.pack('<I',65536));cpu.mem_write(request,struct.pack('<II',0x80960000,8000))
        cpu.mem_write(request+17,bytes([uncached]));cpu.mem_write(request+32,struct.pack('<II',0,endpoint+28))
        cpu.emu_start(0x600c48fe|1,0x600c492a,count=100)
        assert cpu.reg_read(UC_ARM_REG_PC)==0x600c492a
        args=[cpu.reg_read(reg) for reg in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
        cache_argument=int.from_bytes(cpu.mem_read(cpu.reg_read(UC_ARM_REG_SP),4),'little')
        assert args==[controller+0x3b6,endpoint,0x80960000,8000] and cache_argument==int(not uncached)
        policies.append(dict(uncached=uncached,DMA_start_call='0x600c492a',arguments=[hex(v) for v in args],cache_argument=cache_argument,payload_not_mapped=True))
    for f in functions.values():del f['code']
    deps=[Path(__file__),sdk,pac,ROOT/'firmware/sdr_receiver/cp_usb_8910.c',ROOT/'firmware/sdr_receiver/iq_udc_adapter.c']
    report=dict(status='passed',device_accessed=False,hardware_tested=False,
        scope='PAC byte identity plus actual ARM helper/scheduling slices; CP15 recorded and DMA start not executed. No wall-time, CPU cycle, cache/MMU hardware or physical throughput proof.',
        functions=functions,cache_cases=cases,UDC_policy_cases=policies,
        current_payload_invalidation_lines_per_8000B=250,
        inferred_line_operations_per_second_at_BW2_budget=250*(30720000//8000),
        next_action='Keep cache ownership checks. Actual duration of payload invalidate, enqueue/completion and CP release must be measured separately before choosing optimization.',
        dependencies={p.relative_to(ROOT).as_posix():sha(p) for p in deps})
    output=ROOT/'records/usb/bw2-v8-dma-cache-native-verification.json';output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status='passed',PAC_matched_functions=len(functions),cache_cases=len(cases),UDC_policy_cases=len(policies),BW2_budget_line_operations=report['inferred_line_operations_per_second_at_BW2_budget']),indent=2))
if __name__=='__main__':main()
