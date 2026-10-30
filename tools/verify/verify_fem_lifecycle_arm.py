"""Execute linked CP FEM wrappers/configuration and inspect lifecycle ordering."""
import argparse,hashlib,json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/host-test-deps'))
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_MEM_WRITE,UC_HOOK_MEM_READ,UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();directory=args.directory.resolve()
    assert not args.output.exists()
    build=json.loads((directory/'build.json').read_text())
    assert build['experimental_fem_override']
    resident=directory/'resident.elf'
    with resident.open('rb') as f:
        e=ELFFile(f);symbols=e.get_section_by_name('.symtab')
        sy={s.name:s['st_value'] for s in symbols.iter_symbols()}
        segments=[(s['p_vaddr'],s.data()) for s in e.iter_segments() if s['p_type']=='PT_LOAD' and s['p_filesz']]
        symbol=symbols.get_symbol_by_name('transaction')[0];a=symbol['st_value']&~1
        section=e.get_section(symbol['st_shndx'])
        data=section.data()[a-section['sh_addr']:a-section['sh_addr']+symbol['st_size']]
    decoder=Cs(CS_ARCH_ARM,CS_MODE_THUMB);decoder.skipdata=True
    instructions=list(decoder.disasm(data,a))
    calls={name:[i.address for i in instructions if i.mnemonic in ('bl','blx') and i.op_str=='#'+hex(sy[name]&~1)]
        for name in ('force_idle','terminal_fem_begin','terminal_fem_end')}
    assert len(calls['force_idle'])==2 and len(calls['terminal_fem_begin'])==len(calls['terminal_fem_end'])==1
    # Compiler may outline/reorder blocks; numeric order alone isn't a proof.
    # Follow the successful force_idle conditional edge to the restore call.
    stop=next(i for i in instructions if i.address==calls['force_idle'][1])
    at=instructions.index(stop)
    assert instructions[at+1].mnemonic=='cmp' and instructions[at+1].op_str=='r0, #0'
    assert instructions[at+2].mnemonic.startswith('beq')
    assert int(instructions[at+2].op_str.lstrip('#'),16)==calls['terminal_fem_end'][0]
    begin_index=next(i for i,x in enumerate(instructions) if x.address==calls['terminal_fem_begin'][0])
    assert any(x.mnemonic=='cbz' for x in instructions[begin_index+1:begin_index+4])
    meta,cfg,ring=0x8097f800,0x8097f900,0x8096e300
    mailbox=int(build['ap_mailbox'],0);generation=int(build['generation'],0)
    cases=[]
    def machine():
        cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM)
        cpu.mem_map(0x80000000,0x1000000);cpu.mem_map(0x50000000,0x40000)
        for address,content in segments:cpu.mem_write(address,content)
        return cpu
    def put(cpu,address,*v):cpu.mem_write(address,struct.pack('<'+'I'*len(v),*v))
    def words(cpu,address,count):return struct.unpack('<'+'I'*count,cpu.mem_read(address,4*count))
    def call(cpu,name,r0=0):
        cpu.reg_write(UC_ARM_REG_R0,r0);cpu.reg_write(UC_ARM_REG_SP,0x80eff000);cpu.reg_write(UC_ARM_REG_LR,0x70000000)
        cpu.emu_start(sy[name]|1,0x70000000,count=100000)
        assert cpu.reg_read(UC_ARM_REG_PC)==0x70000000
        return cpu.reg_read(UC_ARM_REG_R0)
    for row in (4,6):
        for mode in (0,1,2):
            cpu=machine();address=0x500097f0 if row==4 else 0x50009810
            original=0xd0005 if row==4 else 0xd0002
            put(cpu,0x500010e8,0x0120506f);put(cpu,0x50007e18,0x96b0)
            put(cpu,0x804f42b8+0x310+16*row,original);put(cpu,address,original)
            cpu.mem_write(0x804f42b8+0x20+2*row,struct.pack('<H',5 if row==4 else 8))
            put(cpu,cfg+44,mode);writes=[]
            cpu.hook_add(UC_HOOK_MEM_WRITE,lambda c,a,p,n,v,x:writes.append((p,n,v)),begin=0x50000000,end=0x5003ffff)
            assert call(cpu,'terminal_fem_begin',row)==0
            assert words(cpu,meta+172,1)==(int(mode!=0),)
            replacement=original if not mode else 0xd0000|(2 if mode==1 else 5)
            assert words(cpu,address,1)==(replacement,)
            assert call(cpu,'terminal_fem_end')==0
            assert words(cpu,address,1)==(original,) and words(cpu,meta+172,1)==(0,)
            assert all(p==address and n==1 for p,n,v in writes)
            assert (not writes) if not mode else bool(writes)
            cases.append(dict(case='linked_begin_end',row=row,mode=mode,RF_writes=writes))
    for kind in ('active','bad_signature','bad_mode','bad_row','restore_conflict'):
        cpu=machine();put(cpu,cfg+44,1)
        if kind=='active':put(cpu,meta+172,1)
        if kind=='bad_mode':put(cpu,cfg+44,3)
        if kind=='restore_conflict':
            put(cpu,meta+160,0x500097f0,0xd0005,0xd0002,1);put(cpu,0x500097f0,0xd0003)
            result=call(cpu,'terminal_fem_end');assert result==0xfffffffc
            assert words(cpu,meta+172,1)==(1,)
        else:
            result=call(cpu,'terminal_fem_begin',7 if kind=='bad_row' else 4)
            assert result!=0
        assert words(cpu,meta+176,1)==(result,)
        cases.append(dict(case=kind,result=hex(result)))
    # Execute the linked transaction continuation after final force_idle.
    # Stop at the real failure-handler entry or the next stage5 trace entry;
    # hardware teardown/publishing and idle itself are deliberately not mocked
    # into a claim of successful DMA stop or complete HELD reachability.
    restore_index=next(i for i,x in enumerate(instructions) if x.address==calls['terminal_fem_end'][0])
    initial_idle_index=next(i for i,x in enumerate(instructions) if x.address==calls['force_idle'][0])
    failure_call=next(x for x in instructions[initial_idle_index+1:initial_idle_index+8] if x.mnemonic=='bl')
    failure_entry=int(failure_call.op_str.lstrip('#'),16)
    trace_call=next(x for x in instructions[restore_index+1:restore_index+14] if x.mnemonic=='bl')
    trace_entry=int(trace_call.op_str.lstrip('#'),16)
    for kind in ('idle_failed','inactive','restore_ok','conflict','bad_state','restore_readback_failed'):
        cpu=machine();target=0x500097f0
        if kind!='inactive':
            put(cpu,meta+160,target,0xd0005,0xd0002,1);put(cpu,target,0xd0002)
        if kind=='conflict':put(cpu,target,0xd0003)
        if kind=='bad_state':put(cpu,meta+160,0x50009900)
        events=[];restoration_write=[False]
        def wrote(c,access,address,size,value,context):
            restoration_write[0]=True
        def readback(c,access,address,size,value,context):
            if kind=='restore_readback_failed' and restoration_write[0]:put(c,target,0xd0002)
        def reached(c,address,size,context):
            if address in (failure_entry,trace_entry):
                events.append(('failure' if address==failure_entry else 'trace',c.reg_read(UC_ARM_REG_R0)))
                c.emu_stop()
        cpu.hook_add(UC_HOOK_MEM_WRITE,wrote,begin=target,end=target+3)
        cpu.hook_add(UC_HOOK_MEM_READ,readback,begin=target,end=target+3)
        cpu.hook_add(UC_HOOK_CODE,reached)
        cpu.reg_write(UC_ARM_REG_R0,1 if kind=='idle_failed' else 0)
        cpu.reg_write(UC_ARM_REG_SP,0x80eff000)
        cpu.emu_start(instructions[at+1].address|1,0x70000000,count=10000)
        failed=kind not in ('inactive','restore_ok')
        expected=[('failure',0xa05 if kind=='idle_failed' else 0xa0d)] if failed else [('trace',5)]
        assert events==expected,(kind,events)
        assert words(cpu,meta+172,1)==(int(failed),),(kind,words(cpu,meta+172,1))
        if kind=='restore_ok':assert words(cpu,target,1)==(0xd0005,)
        if kind=='idle_failed':assert not restoration_write[0] and words(cpu,target,1)==(0xd0002,)
        cases.append(dict(case='linked_stop_continuation',scenario=kind,terminal_event=events,
            active=words(cpu,meta+172,1)[0],result=hex(words(cpu,meta+176,1)[0])))
    for channel,mode,phase,active,expected in ((2525,0,30,0,0),(2525,1,30,0,0),(2525,2,30,0,0),
        (3625,1,30,0,0),(3625,2,30,0,0),(38950,1,30,0,0xc17),
        (1575,2,30,0,0xc17),(2525,3,30,0,0xc17),(2525,1,27,0,0xc17),
        (2525,0,30,1,0xc17),(2525,1,30,1,0xc17)):
        cpu=machine();packed=channel|(40<<19)|(mode<<26)
        put(cpu,cfg,0,2,1,2525,0,40,0,0,30720,0,0,0)
        put(cpu,meta+12,phase);put(cpu,meta+172,active)
        put(cpu,ring,0x53545231,1,6,1,0,0,0,0,1)
        put(cpu,mailbox,0x52585331,generation,1,13,0,packed,0xfffffffe,1)
        call(cpu,'terminal_stream_poll')
        reply=words(cpu,mailbox+32,8);assert reply[4]==expected,(channel,mode,reply)
        assert words(cpu,meta+124,1)==(0 if expected else 1,)
        assert words(cpu,cfg+44,1)==(0 if expected else mode,)
        if expected:assert words(cpu,cfg+12,3)==(2525,0,40)
        cases.append(dict(case='CONFIG',channel=channel,mode=mode,phase=phase,active=active,error=expected))
    deps=[Path(__file__),directory/'build.json',resident,
        ROOT/'firmware/capture/rxcapt_fem_override.h',ROOT/'firmware/capture/rf_terminal_rx.c',
        ROOT/'firmware/capture/rf_terminal_service.c',ROOT/'firmware/capture/rf_terminal_control.c',
        ROOT/'firmware/rf_rebuild/rf_frontend_override.c',ROOT/'firmware/rf_rebuild/rf_frontend_override.h']
    report=dict(status='passed',device_accessed=False,hardware_tested=False,cases=cases,
        linked_calls=calls,restore_reachable_only_on_successful_RF_stop=True,
        scope='Linked wrappers, stopped CONFIG and post-force_idle transaction continuation executed through real restore to failure/stage5 trace entry. No vendor init/idle, complete teardown/HELD, cache or peripheral timing modeled. AP integration covered separately.',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in deps})
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status='passed',cases=len(cases),resident_bytes=build['resident']['bytes'])))
if __name__=='__main__':main()
