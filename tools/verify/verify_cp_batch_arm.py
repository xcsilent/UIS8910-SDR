"""Execute the rebuilt CP batch mailbox handler in ARM emulation, without RF."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/host-test-deps'))
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC,UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R4,UC_ARM_REG_R5


def verify_lossy_stop_loop(directory, build):
    """Run linked polling/stop tail; bypass RF startup and model MMIO inputs.

    Enter immediately after publish(T_POLL), with its compiler frame seeded.
    Actual loop, paired completion and inlined restore/error path execute.
    DMA motion/cache/RF are not modeled. Successful stop cases use explicit
    RUN-clear, W1C and allocator stubs, not proof of peripheral semantics.
    """
    import subprocess
    gcc=ROOT/'inputs/repositories/rda8910-csdk-hotelec/prebuilts/win32/gcc-arm-none-eabi/bin'
    dis=subprocess.check_output([str(gcc/'arm-none-eabi-objdump.exe'),'-d',str(directory/'resident.elf')],text=True)
    tail=dis.split('<transaction>:',1)[1].split('<terminal_dispatch>:',1)[0]
    # This reviewed frame contract must fail if a compiler changes it.
    assert re.search(r'sub\s+sp, #148',tail)
    entry=re.search(r'movs\s+r0, #27\s*\n\s*[0-9a-f]+:.*?bl\s+[0-9a-f]+ <publish>\s*\n\s*([0-9a-f]+):.*?ldr\s+r0, \[r4, #20\]',tail)
    assert entry, 'review polling-tail frame before updating this test'
    fem_override=build.get('experimental_fem_override',False)
    if fem_override:
        # Reviewed new frame: successful FEM begin returns0, saved as initial
        # complete at sp+12. DMA-idle success explicitly sets it to1. sp+8
        # is now the adopt_initial result, not complete. Keep old build gate.
        assert re.search(r'bl\s+[0-9a-f]+ <terminal_fem_begin>\s*\n.*?str\s+r0, \[sp, #12\]',tail)
        assert re.search(r'bl\s+[0-9a-f]+ <rxcapt_stream_dma_idle>.*?movs\s+r3, #1\s*\n.*?str\s+r3, \[sp, #12\]',tail,re.S)
        assert re.search(r'ldr\s+r3, \[sp, #12\]\s*\n.*?cbz',tail)
    else:
        assert re.search(r'bl\s+[0-9a-f]+ <rfad_rx_request_plan>\s*\n.*?cmp\s+r0, #1\s*\n.*?str\s+r0, \[sp, #8\]',tail), 'review seeded complete spill'
    cases=[]
    for stuck in ('head','data','response_error','head_stops','data_stops','complete',
                  'publish_both','publish_data_first','publish_head_first','publish_scratch'):
        publication=stuck.startswith('publish_')
        stops=stuck in ('head_stops','data_stops','complete')
        data_stuck=stuck in ('data','data_stops')
        machine=Uc(UC_ARCH_ARM,UC_MODE_ARM)
        for address,size in ((0x80000000,0x1000000),(0x22000000,0x100000),(0x25000000,0x1000),(0x27000000,0x1000),(0x50000000,0x40000)):
            machine.mem_map(address,size)
        with (directory/'resident.elf').open('rb') as source:
            elf=ELFFile(source)
            sy={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
            for segment in elf.iter_segments():
                if segment['p_type']=='PT_LOAD' and segment['p_filesz']:
                    machine.mem_write(segment['p_vaddr'],segment.data())
        def put(address,*values):machine.mem_write(address,struct.pack('<'+'I'*len(values),*values))
        def word(address):return struct.unpack('<I',machine.mem_read(address,4))[0]
        state=0x8097fa00;ring=0x8096e300;meta=0x8097f800
        data=0x22000100;head=0x22000200
        put(state,0x52434631,1,3,0,0,7,8)
        put(0x80468a48+7*4,data,head)
        put(ring,0x53545231,1,6,0,0,0,0,0,0)
        for i in range(6):put(ring+36+i*12,0xffffffff,0,0)
        put(ring+36,0,3,0)
        put(data,1);put(head,1)
        finish=0x00200000
        put(data+16,8192 if data_stuck else 0,0,1 if data_stuck else finish)
        put(head+16,0 if data_stuck else 24,0,finish if data_stuck else 1)
        if publication:
            # Status is sampled before the first mailbox poll in the actual
            # loop; seed both the sampled and subsequent peripheral state.
            put(data+16,8192 if stuck=='publish_head_first' else 0,0,
                1 if stuck=='publish_head_first' else finish)
            put(head+16,24 if stuck=='publish_data_first' else 0,0,
                1 if stuck=='publish_data_first' else finish)
        counters={'poll':0,'stop_calls':0,'aborted':0,'failed':None,'pair':None,'drained':False,'released':[]}
        counters.update(publications=[],rearms=[])
        # Allocator ownership must remain live until both channels stop.
        put(0x80476740,0x01800000)
        pending_w1c={}
        def mmio_write(m,access,address,size,value,user):
            if address in (data+24,head+24,0x2200000c):
                pending_w1c[address]=word(address)&~value
        def mmio_read(m,access,address,size,value,user):
            if address in pending_w1c:put(address,pending_w1c.pop(address))
        if stops:
            machine.hook_add(UC_HOOK_MEM_WRITE,mmio_write,begin=0x22000000,end=0x220fffff)
            machine.hook_add(UC_HOOK_MEM_READ,mmio_read,begin=0x22000000,end=0x220fffff)
        def return_value(value=0):
            machine.reg_write(UC_ARM_REG_R0,value)
            machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR))
        def hook(m,address,size,user):
            name=user
            if name=='rxcapt_lossy_adopt_initial':counters['pair']=m.reg_read(UC_ARM_REG_R1);return
            if name=='terminal_stream_poll':
                counters['poll']+=1
                if publication:
                    if counters['poll']>1:
                        m.emu_stop();return
                    if stuck=='publish_scratch':
                        put(counters['pair'],6,0,0,1)
                        put(ring+16,6,6,6,0,1)
                        for i in range(6):put(ring+36+i*12,i,0,3)
                        put(ring+28*4,3,0)
                    put(data+16,8192 if stuck=='publish_head_first' else 0,0,
                        1 if stuck=='publish_head_first' else finish)
                    put(head+16,24 if stuck=='publish_data_first' else 0,0,
                        1 if stuck=='publish_data_first' else finish)
                    return_value();return
                # Set up a full output ring and a private scratch reservation.
                if counters['poll']==1:
                    put(counters['pair'],6,0,0,1)
                    put(ring+16,6,6,6,0,1)
                    for i in range(6):put(ring+36+i*12,i,0,3)
                    put(ring+28*4,3,0)
                    if stuck=='response_error':put(head+24,0x02000000)
                put(ring+12,1);put(meta+31*4,counters['poll'])
                if stuck=='complete' and counters['poll']==2:
                    put(head+16,0,0,finish)
                return_value();return
            if name=='terminal_stream_publish' and publication:
                counters['publications'].append([word(ring+24),word(ring+28*4),
                    word(counters['pair']+12),word(counters['pair']+4)])
                # Complete the other channel only after partial state was
                # exported. The following loop iteration must publish it too.
                if len(counters['publications'])==1 and stuck=='publish_data_first':
                    put(head+16,0,0,finish)
                if len(counters['publications'])==1 and stuck=='publish_head_first':
                    put(data+16,0,0,finish)
                return_value();return
            if name=='rxcapt_ring_poll_rearm' and publication:
                channel=m.reg_read(UC_ARM_REG_R0);slot=m.reg_read(UC_ARM_REG_R2)
                counters['rearms'].append([channel,slot])
                # New reservation must already have been exported before
                # either physical arm; do not model real DMA motion here.
                assert counters['publications'][-1][2:]==[1,0],counters
                dma=data if channel==7 else head
                put(dma+16,8192 if channel==7 else 24,0,1)
                return_value(1);return
            if name=='stop_dma_channel':
                counters['stop_calls']+=1
                if stops:
                    dma=data if m.reg_read(UC_ARM_REG_R0)==7 else head
                    put(dma+24,word(dma+24)&~1)
                return
            if name=='rxcapt_stream_dma_aborted':counters['aborted']+=1;return
            if name=='release':
                channel=m.reg_read(UC_ARM_REG_R0)
                assert counters['stop_calls']==2 and not (word(data+24)|word(head+24))
                counters['released'].append(channel)
                put(0x80476740,word(0x80476740)&~(1<<(channel+16)))
                return_value();return
            if name=='terminal_stream_drain':counters['drained']=True;m.emu_stop();return
            if name.startswith('failed'):
                counters['failed']=m.reg_read(UC_ARM_REG_R0);m.emu_stop();return
            if name=='rfad_read_frame_time_bounded':return_value(1);return
            return_value()
        names=('rxcapt_lossy_adopt_initial','terminal_stream_poll','stop_dma_channel','rxcapt_stream_dma_aborted',
               'force_idle','clean_range','publish','proof','rfad_read_frame_time_bounded',
               'terminal_stream_drain',next(n for n in sy if n.startswith('failed')))
        for name in names:
            address=sy[name]&~1
            machine.hook_add(UC_HOOK_CODE,hook,name,begin=address,end=address)
        if publication:
            for name in ('terminal_stream_publish','rxcapt_ring_poll_rearm'):
                address=sy[name]&~1
                machine.hook_add(UC_HOOK_CODE,hook,name,begin=address,end=address)
        if stops:
            # Vendor HAL count-clear/LPS/release are explicit external stubs.
            for address,name in ((0x802fffa0,'count_clear'),(0x802fe9ac,'lps'),(0x802fff8c,'release')):
                machine.hook_add(UC_HOOK_CODE,hook,name,begin=address,end=address)
        machine.reg_write(UC_ARM_REG_SP,0x80eff000)
        put(0x80eff000+0x50,0,sy['raw_read'],sy['raw_write'])
        # Compiler hoists the normal-exit complete value before T_POLL;
        # timeout/error exits explicitly overwrite this spill with zero.
        put(0x80eff000+(12 if fem_override else 8),0 if fem_override else 1)
        machine.reg_write(UC_ARM_REG_R4,state);machine.reg_write(UC_ARM_REG_R5,0)
        machine.emu_start(int(entry[1],16)|1,0,timeout=30000000,count=40000000)
        if publication:
            assert counters['poll']==2 and counters['failed'] is None,counters
            expected=2 if stuck in ('publish_data_first','publish_head_first') else 1
            assert len(counters['publications'])==expected,counters
            slot=6 if stuck=='publish_scratch' else 1
            assert counters['rearms']==[[7,slot],[8,slot]],counters
            assert word(ring+24)==(6 if slot==6 else 1),counters
            assert word(ring+29*4)==(1 if slot==6 else 0),counters
            assert word(ring+28*4)==(3 if slot==6 else 0),counters
            cases.append(dict(case=stuck,publications=expected,rearms=counters['rearms'],
                              reservation_published_before_arm=True,
                              scope='linked loop; publication and DMA rearm stubbed, no cache/hardware timing proof'))
            continue
        if stops:
            assert counters['drained'] and counters['failed'] is None and counters['released']==[7,8],(counters,hex(machine.reg_read(UC_ARM_REG_PC)))
            assert word(0x80476740)==0 and word(ring+28*4)==0
            assert counters['aborted']==(0 if stuck=='complete' else 1),(stuck,counters,word(state+8),word(ring+28*4),word(ring+29*4))
            assert word(state+8)==(6 if stuck=='complete' else 9)
            assert word(ring+29*4)==(1 if stuck=='complete' else 0)
            # Independently execute the real initializer after teardown; this
            # is fresh metadata only, not vendor RF/DMA rearming.
            machine.reg_write(UC_ARM_REG_R0,ring);machine.reg_write(UC_ARM_REG_R1,6)
            machine.reg_write(UC_ARM_REG_SP,0x80eff000);machine.reg_write(UC_ARM_REG_LR,0x80ee0000)
            machine.emu_start(sy['rxcapt_stream_state_init']|1,0x80ee0000,count=10000)
            assert machine.reg_read(UC_ARM_REG_PC)==0x80ee0000 and machine.reg_read(UC_ARM_REG_R0)==1
            assert word(ring+12)==0 and word(ring+28*4)==0 and word(ring+29*4)==0
            assert word(ring+40)==3 and word(ring+24)==0
            cases.append(dict(fault=stuck,mailbox_renewals=counters['poll'],stop_calls=2,
                              released_channels=counters['released'],abort_cleanup=counters['aborted'],
                              final_phase='held' if stuck=='complete' else 'failed',fresh_metadata_initialized=True))
            continue
        assert counters['failed']==0xa06 and counters['stop_calls']==2 and not counters['aborted'],counters
        assert word(state+8)==8 and word(state+12)==(0x301 if stuck=='data' else 0x306 if stuck=='response_error' else 0x302)
        assert word(ring+28*4) & 3 and word(ring+29*4)==0,(stuck,counters,word(ring+28*4),word(ring+29*4))
        if stuck!='response_error':assert counters['poll']>1000,counters
        cases.append(dict(fault=stuck,mailbox_renewals=counters['poll'],stop_calls=counters['stop_calls'],
                          phase='pinned',error=hex(word(state+12)),scratch_ownership_retained=True))
    return cases


def verify(directory):
    directory=directory.resolve()
    build=json.loads((directory/'build.json').read_text(encoding='utf-8'))
    # The byte ring is independent of RF mode. Its first following live region
    # is STREAM at e300, earlier than the old f800 DATA limit. Enlarging slots
    # without moving that state would corrupt ownership even if DMA fits.
    abi=(ROOT/'firmware/capture/rxcapt_finite_abi.h').read_text()
    default_bytes=int(re.search(r'#define RXCAPT_FINITE_DATA_BYTES (\d+)u',abi)[1])
    default_end=int(re.search(r'#define RXCAPT_FINITE_CAPTURE_END_ADDRESS (\d+)u',abi)[1])
    slot_bytes=build.get('slot_bytes',default_bytes)
    capture_end=default_end if slot_bytes==default_bytes else slot_bytes//4-1
    recipe=json.loads((ROOT/'firmware/capture/build-recipe.json').read_text())
    definitions=[v for v in recipe['commands'][0] if isinstance(v,str)]
    stream_address=int(next(v.split('=')[1].rstrip('u') for v in definitions if v.startswith('-DRXCAPT_STREAM_STATE_ADDRESS=')),0)
    assert slot_bytes==(capture_end+1)*4
    assert 0x80960000+7*slot_bytes<=stream_address
    trace=build.get('rf_status_trace',{})
    if trace.get('enabled'):
        assert 0x80960000+7*slot_bytes<=int(trace['address'],0)
    assert stream_address+30*4<=0x8096f800 and 0x8096ff00+7*24<=0x80970000
    assert build['resident']['bytes']<=0x4000 and build['control']['bytes']<=0x2000
    resident=ROOT/build['resident']['path']
    if hashlib.sha256(resident.read_bytes()).hexdigest()!=build['resident']['sha256']:
        raise ValueError('CP batch binary changed')
    if hashlib.sha256((ROOT/build['control']['path']).read_bytes()).hexdigest()!=build['control']['sha256']:
        raise ValueError('CP control binary changed')
    elf_path=directory/'resident.elf'
    uc=Uc(UC_ARCH_ARM,UC_MODE_ARM)
    uc.mem_map(0x80000000,0x1000000)
    uc.mem_map(0x70000000,0x1000)
    with elf_path.open('rb') as stream:
        elf=ELFFile(stream)
        symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        for segment in elf.iter_segments():
            if segment['p_type']=='PT_LOAD' and segment['p_filesz']:
                uc.mem_write(segment['p_vaddr'],segment.data())
    uc.hook_add(UC_HOOK_CODE,lambda machine,address,size,_:machine.emu_stop() if address==0x70000000 else None)
    mailbox=int(build['ap_mailbox'],0)
    generation=int(build['generation'],0)
    state=0x8096e300
    meta=0x8097f800
    export=0x8096fa40
    def put(address,*words):
        uc.mem_write(address,struct.pack('<'+'I'*len(words),*words))
    def words(address,count):
        return struct.unpack('<'+'I'*count,uc.mem_read(address,count*4))
    def command(sequence,previous,operation,block):
        put(mailbox,0x52585331,generation,sequence,operation,previous,block,(~sequence)&0xffffffff,sequence)
        uc.reg_write(UC_ARM_REG_SP,0x80eff000)
        uc.reg_write(UC_ARM_REG_LR,0x70000000)
        uc.emu_start(symbols['terminal_stream_poll']|1,0x70000000,timeout=2000000,count=100000)
        if uc.reg_read(UC_ARM_REG_PC)!=0x70000000:
            raise RuntimeError('CP batch mailbox handler did not return')
        return words(mailbox+32,8)
    put(state,0x53545231,1,7,0,3,3,3,0,0)
    for i in range(7):
        put(state+36+i*12,i if i<3 else 0xffffffff,0,3 if i<3 else 0)
    put(meta+12,24)
    cases=[]
    if build.get('experimental_lossy_scratch'):
        def call_resident(name, *args):
            for register,value in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),args):
                uc.reg_write(register,value)
            uc.reg_write(UC_ARM_REG_SP,0x80eff000)
            uc.reg_write(UC_ARM_REG_LR,0x70000000)
            uc.emu_start(symbols[name]|1,0x70000000,timeout=2000000,count=100000)
            if uc.reg_read(UC_ARM_REG_PC)!=0x70000000:raise RuntimeError(name+' did not return')
            return uc.reg_read(UC_ARM_REG_R0)
        put(state,0x53545231,1,6,1,0,0,0,0,1)
        put(state+28*4,3,0)
        assert call_resident('rxcapt_stream_dma_idle',state)==0
        put(state+28*4,1,0)
        assert call_resident('rxcapt_stream_dma_idle',state)==0
        # Models the call only after both physical DMAs have been stopped;
        # the emulator does not establish that hardware condition.
        assert call_resident('rxcapt_stream_dma_aborted',state,4)==1
        assert call_resident('rxcapt_stream_dma_idle',state)==1
        cases.append('scratch activity blocks resident idle, post-stop abort clears it (physical stop not emulated)')
        pair=0x80ee1000
        fake_arm=0x70000100
        calls=[]
        failure=[0]
        def emulate_arm(machine,address,size,user):
            if address!=fake_arm:return
            calls.append((machine.reg_read(UC_ARM_REG_R0),machine.reg_read(UC_ARM_REG_R1),machine.reg_read(UC_ARM_REG_R2)))
            machine.reg_write(UC_ARM_REG_R0,0 if len(calls)==failure[0] else 1)
            machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR))
        hook=uc.hook_add(UC_HOOK_CODE,emulate_arm)
        for fail_at,expected in ((1,1),(2,2),(0,2)):
            calls.clear();failure[0]=fail_at;put(pair,6,0,0,1)
            result=call_resident('rxcapt_lossy_arm_reserved',pair,7,8,fake_arm|1)
            assert result==(0 if fail_at else 1) and len(calls)==expected
            assert calls[0]==(7,0,6) and (len(calls)<2 or calls[1]==(8,1,6))
            assert words(pair,4)==(6,0,0,1)
        uc.hook_del(hook)
        cases.append('actual ARM paired arm: first/second failure preserves reservation; no physical stop emulated')
        put(state,0x53545231,1,7,0,3,3,3,0,0)
        for i in range(7):put(state+36+i*12,i if i<3 else 0xffffffff,0,3 if i<3 else 0)
    if build.get('until_stop_supported'):
        scratch=0x80ee0000;put(scratch,0,0)
        for elapsed,cursor,expired in [(0,0,0),(4999,0,0),(5000,0,1),
                                      (200000,1,0),(204999,1,0),(205000,1,1),(10,1,0)]:
            put(meta+31*4,cursor)
            for reg,value in [(UC_ARM_REG_R0,elapsed),(UC_ARM_REG_R1,scratch),(UC_ARM_REG_R2,scratch+4),
                              (UC_ARM_REG_SP,0x80eff000),(UC_ARM_REG_LR,0x70000000)]:uc.reg_write(reg,value)
            uc.emu_start(symbols['terminal_stream_timeout_expired']|1,0x70000000,count=10000)
            assert uc.reg_read(UC_ARM_REG_PC)==0x70000000 and uc.reg_read(UC_ARM_REG_R0)==expired
        put(meta+31*4,0)
        cases.append('CP activity watchdog expires at5000frame units, accepted cursor progress renews beyond old200000 limit, RF frame wrap handled')
    reply=command(1,0,11,0)
    assert reply==(0x52585331,generation,1,11,0,0,3,1)
    assert words(meta+31*4,1)==(1,)
    assert all(words(state+36+i*12,3)==(i,4,3) for i in range(3))
    assert words(export,3)==(0x53545231,1,7)
    assert all(words(export+36+i*12,3)==(i,4,3) for i in range(3))
    cases.append('actual CP mailbox op11 claims three slots and publishes ownership')
    assert command(1,0,11,0)==reply
    cases.append('same command sequence retains response without repeating claim')
    reply=command(2,1,12,2)
    assert reply==(0x52585331,generation,2,12,0,2,2,2)
    assert words(state+28,1)==(2,)
    assert words(state+36,6)==(0xffffffff,0,0,0xffffffff,0,0)
    assert words(state+36+2*12,3)==(2,4,3)
    cases.append('actual CP mailbox op12 releases completed prefix while retaining last slot')
    before=bytes(uc.mem_read(state,120))
    reply=command(3,2,12,4)
    assert reply[3:5]==(4,0xc16) and words(meta+31*4,1)==(2,)
    assert bytes(uc.mem_read(state,120))==before
    cases.append('out-of-range release rejects without mutating ownership or command cursor')
    reply=command(3,2,12,3)
    assert reply==(0x52585331,generation,3,12,0,3,3,3)
    assert words(state+28,1)==(3,)
    cases.append('corrected next command drains remaining batch')
    reply=command(5,3,11,3)
    assert reply[3:5]==(4,0xc10) and words(meta+31*4,1)==(3,)
    cases.append('skipped AP command sequence rejected')
    if build.get('native_restart_implemented'):
        # CP may rearm only after native RF teardown and complete release.
        before=bytes(uc.mem_read(state,120))
        if build.get('precapture_config_implemented'):
            reply=command(4,3,13,2526|(20<<19))
            assert reply[3:5]==(4,0xc17) and words(meta+31*4,1)==(3,)
            assert bytes(uc.mem_read(state,120))==before
            cases.append('CONFIG rejected while RF is not stopped/drained')
        reply=command(4,3,9,8815000)
        assert reply[3:5]==(4,0xc12) and words(meta+31*4,1)==(3,)
        assert bytes(uc.mem_read(state,120))==before
        cases.append('REARM rejected before stopped/drained proof without state or cursor mutation')
        put(meta+12,30)
        put(state+12,1)
        put(state+32,1)
        put(meta+32*4,1)
        put(0x8097f900+4,2,1,2525,0,40)
        packed=2526|(20<<19)
        reply=command(4,3,13,packed)
        assert reply==(0x52585331,generation,4,13,0,packed,packed,4)
        assert words(0x8097f900+12,3)==(2526,0,20)
        cases.append('stopped CONFIG changes B5 anchor and gain without starting RF')
        reply=command(5,4,9,8816000)
        assert reply==(0x52585331,generation,5,9,0,8816000,2,5)
        assert words(state,30)==(0,)*30 and words(export,30)==(0,)*30
        assert words(meta+35*4,1)==(1,) and words(meta+31*4,1)==(5,)
        cases.append('drained native REARM clears old private/exported epoch before ACK and retains command cursor')
        if build.get('multi_profile_implemented'):
            put(state,0x53545231,1,7,1,0,0,0,0,1)
            packed=38950|(40<<19)
            reply=command(6,5,13,packed)
            assert reply[3:7]==(13,0,packed,packed)
            assert words(0x8097f900+12,3)==(38950,0,40)
            # A B5 raw center must not leak into the newly selected A route.
            reply=command(7,6,9,42949673 if build.get('unrestricted_frequency') else 8815000)
            assert reply[3:5]==(4,0xc13) and words(meta+31*4,1)==(6,)
            reply=command(7,6,9,20000000)
            assert reply[3:7]==(9,0,20000000,2)
            assert words(0x8097f900+36,1)==(20000000,)
            assert words(state,30)==(0,)*30
            cases.append('B40 anchor remains 38950 while raw 2 GHz is accepted; cross-route B5 raw rejected')
            if 3 in build.get('rf_profiles',[]) and 8 in build.get('rf_profiles',[]):
                sequence=8
                for channel,raw,foreign in ((1575,18425000,9425000),(3625,9425000,18425000)):
                    put(meta+12,30)
                    put(state,0x53545231,1,7,1,0,0,0,0,1)
                    packed=channel|(30<<19)
                    reply=command(sequence,sequence-1,13,packed)
                    assert reply[3:7]==(13,0,packed,packed)
                    assert words(0x8097f900+12,3)==(channel,0,30)
                    sequence+=1
                    assert command(sequence,sequence-1,9,42949673 if build.get('unrestricted_frequency') else foreign)[3:5]==(4,0xc13)
                    reply=command(sequence,sequence-1,9,raw)
                    assert reply[3:7]==(9,0,raw,2)
                    assert words(0x8097f900+36,1)==(raw,) and words(state,30)==(0,)*30
                    sequence+=1
                cases.append('B3 and B8 drained CONFIG/REARM preserve native channel/gain and reject foreign-route centers')
            # Exercise the actual control gate used for first launch as well.
            with (directory/'control.elf').open('rb') as stream:
                control_elf=ELFFile(stream)
                control_symbols={s.name:s['st_value'] for s in control_elf.get_section_by_name('.symtab').iter_symbols()}
                for segment in control_elf.iter_segments():
                    if segment['p_type']=='PT_LOAD' and segment['p_filesz']:
                        uc.mem_write(0x80975000+segment['p_vaddr'],segment.data())
            for channel,raw,accepted in ((38950,18843750,1),(38950,27906250,1),
                (38950,18843749,0),(38950,27906251,0),(38950,20000000,1),
                (2525,8815000,1),(2525,8240000,1),(2525,7000000,1),(2525,5000000,1),(2525,9250000,1),
                (2525,4999999,0),(2525,9250001,0),(2525,20000000,0),(38949,23300000,0)):
                put(0x8097f900,0,2,1,channel,0,40,0,0,30720,raw)
                uc.reg_write(UC_ARM_REG_SP,0x80eff000)
                uc.reg_write(UC_ARM_REG_LR,0x70000000)
                uc.emu_start((0x80975000+control_symbols['valid_stream_profile'])|1,0x70000000,timeout=2000000,count=100000)
                assert uc.reg_read(UC_ARM_REG_PC)==0x70000000
                if build.get('unrestricted_frequency'):accepted=int(channel!=38949 and raw<=42949672)
                assert uc.reg_read(UC_ARM_REG_R0)==accepted,(channel,raw,accepted)
            cases.append('compiled first-launch gate checks B5/B40 envelopes independently, including endpoints and invalid anchors')
            if 3 in build.get('rf_profiles',[]):
                b3_min=(build.get('experimental_b3_min_hz') or 1710000000)//100
                for channel,raw,accepted in ((1200,18050000,1),(1949,18799000,1),
                    (1575,18425001,1),(1575,17100000,1),(1575,19200000,1),
                    (1575,b3_min,1),(1575,b3_min-1,0),(1575,17099999,int(b3_min<17100000)),(1575,19200001,0),
                    (3450,9250000,1),(3799,9599000,1),(3625,9425001,1),
                    (3625,8800000,1),(3625,10000000,1),(3625,8799999,0),(3625,10000001,0),(3625,18425000,0)):
                    put(0x8097f900,0,2,1,channel,0,40,0,0,30720,raw)
                    uc.reg_write(UC_ARM_REG_SP,0x80eff000)
                    uc.reg_write(UC_ARM_REG_LR,0x70000000)
                    uc.emu_start((0x80975000+control_symbols['valid_stream_profile'])|1,0x70000000,timeout=2000000,count=100000)
                    assert uc.reg_read(UC_ARM_REG_PC)==0x70000000
                    if build.get('unrestricted_frequency'):accepted=int(raw<=42949672)
                    assert uc.reg_read(UC_ARM_REG_R0)==accepted,(channel,raw,accepted)
                cases.append('compiled B3/B8 first-launch validation checks table edges and independent 100-Hz raw centers')
            if 1 in build.get('rf_profiles',[]):
                sequence=12
                for channel,raw,lower,upper in ((300,21400000,21100000,21699000),
                    (38000,25950000,25700000,26199000),(38450,19000000,18800000,19199000),
                    (40640,25950000,24960000,26899000)):
                    put(meta+12,30);put(state,0x53545231,1,7,1,0,0,0,0,1)
                    packed=channel|(20<<19)
                    assert command(sequence,sequence-1,13,packed)[3:7]==(13,0,packed,packed)
                    assert words(0x8097f900+12,3)==(channel,0,20)
                    sequence+=1
                    assert command(sequence,sequence-1,9,42949673 if build.get('unrestricted_frequency') else 8815000)[3:5]==(4,0xc13)
                    assert command(sequence,sequence-1,9,raw)[3:7]==(9,0,raw,2)
                    sequence+=1
                    for value,accepted in ((lower,1),(upper,1),(lower-1,0),(upper+1,0),(raw+1,1)):
                        put(0x8097f900,0,2,1,channel,0,40,0,0,30720,value)
                        uc.reg_write(UC_ARM_REG_SP,0x80eff000);uc.reg_write(UC_ARM_REG_LR,0x70000000)
                        uc.emu_start((0x80975000+control_symbols['valid_stream_profile'])|1,0x70000000,timeout=2000000,count=100000)
                        assert uc.reg_read(UC_ARM_REG_PC)==0x70000000
                        if build.get('unrestricted_frequency'):accepted=int(value<=42949672)
                        assert uc.reg_read(UC_ARM_REG_R0)==accepted,(channel,value)
                cases.append('B1/B38/B39/B41 CONFIG/REARM and first-launch gates use fixed anchors with independent raw centers and bounded envelopes')
            if 7 in build.get('rf_profiles',[]):
                sequence=20
                for channel,raw,lower,upper in ((3100,26550000,26200000,26899000),
                    (5925,8675000,8600000,8749000),(6075,8825000,8750000,8899000),
                    (8865,8765000,8590000,8939000)):
                    put(meta+12,30);put(state,0x53545231,1,7,1,0,0,0,0,1)
                    packed=channel|(60<<19)
                    assert command(sequence,sequence-1,13,packed)[3:7]==(13,0,packed,packed)
                    assert words(0x8097f900+12,3)==(channel,0,60)
                    sequence+=1
                    assert command(sequence,sequence-1,9,42949673 if build.get('unrestricted_frequency') else 9599000)[3:5]==(4,0xc13)
                    assert command(sequence,sequence-1,9,raw)[3:7]==(9,0,raw,2)
                    sequence+=1
                    for value,accepted in ((lower,1),(upper,1),(lower-1,0),(upper+1,0),(raw+1,1)):
                        put(0x8097f900,0,2,1,channel,0,40,0,0,30720,value)
                        uc.reg_write(UC_ARM_REG_SP,0x80eff000);uc.reg_write(UC_ARM_REG_LR,0x70000000)
                        uc.emu_start((0x80975000+control_symbols['valid_stream_profile'])|1,0x70000000,timeout=2000000,count=100000)
                        assert uc.reg_read(UC_ARM_REG_PC)==0x70000000
                        if build.get('unrestricted_frequency'):accepted=int(value<=42949672)
                        assert uc.reg_read(UC_ARM_REG_R0)==accepted,(channel,value)
                cases.append('B7/B18/B19/B26 stopped CONFIG/REARM and first-launch bounds preserve explicit anchor and independent raw center')
            if 34 in build.get('rf_profiles',[]):
                last=words(meta+31*4,1)[0];sequence=last+1
                put(meta+12,30);put(state,0x53545231,1,7,1,0,0,0,0,1)
                packed=36275|(40<<19)
                assert command(sequence,last,13,packed)[3:7]==(13,0,packed,packed)
                assert command(sequence+1,sequence,9,20175000)[3:7]==(9,0,20175000,2)
                for value,accepted in ((20100000,1),(20249000,1),(20175001,1),(20099999,0),(20249001,0),(8815000,0)):
                    put(0x8097f900,0,2,1,36275,0,40,0,0,30720,value)
                    uc.reg_write(UC_ARM_REG_SP,0x80eff000);uc.reg_write(UC_ARM_REG_LR,0x70000000)
                    uc.emu_start((0x80975000+control_symbols['valid_stream_profile'])|1,0x70000000,timeout=2000000,count=100000)
                    if build.get('unrestricted_frequency'):accepted=int(value<=42949672)
                    assert uc.reg_read(UC_ARM_REG_R0)==accepted,(36275,value)
                cases.append('B34 CONFIG/REARM and first-launch checks preserve36275 anchor,100Hz center and explicit bounds; NV guard checked separately')
    if build.get('precapture_config_implemented'):
        allowed=build.get('bandwidth_indices',[0])
        for bw in list(range(max(allowed)+2))+list(reversed(allowed)):
            last=words(meta+31*4,1)[0];sequence=last+1
            put(meta+12,30);put(meta+32*4,1)
            put(state,0x53545231,1,7,1,0,0,0,0,1)
            put(0x8097f900,0,2,1,2525,0,40,0,0,30720,8815000)
            before=bytes(uc.mem_read(0x8097f900,40))
            packed=2525|(bw<<16)|(40<<19)
            reply=command(sequence,last,13,packed)
            if bw not in allowed:
                assert reply[3:5]==(4,0xc17) and words(meta+31*4,1)[0]==last
                assert bytes(uc.mem_read(0x8097f900,40))==before
            else:
                assert reply[3:7]==(13,0,packed,packed)
                assert words(0x8097f900+12,3)==(2525,bw,40)
                assert command(sequence+1,sequence,9,8815000)[3:7]==(9,0,8815000,2)
                assert words(0x8097f900+16,1)[0]==bw
        cases.append('compiled BW capability bounds reject without config/cursor mutation; each accepted BW rearm retains selected bandwidth')
        if 1 in allowed and build.get('multi_profile_implemented'):
            for bw in range(max(allowed)+2):
                accepted=int(bw in allowed)
                put(0x8097f900,0,2,1,2525,bw,40,0,0,30720,8815000)
                uc.reg_write(UC_ARM_REG_SP,0x80eff000);uc.reg_write(UC_ARM_REG_LR,0x70000000)
                uc.emu_start((0x80975000+control_symbols['valid_stream_profile'])|1,0x70000000,timeout=2000000,count=100000)
                assert uc.reg_read(UC_ARM_REG_R0)==accepted
            cases.append('control first-launch gate accepts exactly the compiled bandwidth capability and rejects the next mode')
    if build.get('experimental_pre_switch'):
        put(meta+12,30);put(state,0x53545231,1,7,1,0,0,0,0,1)
        put(0x8097f900,0,2,1,38950,0,40,0,0,30720,20000000,5)
        for selector in (5,6,7):
            last=words(meta+31*4,1)[0];seq=last+1
            packed=38950|(5<<16)|(40<<19)|(selector<<26)
            assert command(seq,last,13,packed)[3:7]==(13,0,packed,packed)
            assert words(0x8097f900+16,1)==(5,) and words(0x8097f900+40,1)==(selector,)
        for bad in ((4<<26)|(5<<16),(6<<26)|(4<<16),(1<<29)|(5<<16)):
            last=words(meta+31*4,1)[0];before=bytes(uc.mem_read(0x8097f900,44))
            assert command(last+1,last,13,38950|(40<<19)|bad)[3:5]==(4,0xc17)
            assert bytes(uc.mem_read(0x8097f900,44))==before and words(meta+31*4,1)==(last,)
        put(meta+12,24);last=words(meta+31*4,1)[0]
        assert command(last+1,last,13,38950|(5<<16)|(40<<19)|(6<<26))[3:5]==(4,0xc17)
        assert words(meta+31*4,1)==(last,)
        cases.append('experimental PRE5/6/7 change only on stopped/drained CONFIG while RF mode stays5; invalid combinations and active RF reject without mutation')
    if 'rxcapt_stream_exchange_batch' in symbols:
        last=words(meta+31*4,1)[0];seq=last+1
        put(state,0x53545231,1,7,0,3,3,4,0,0)
        for n in range(7):put(state+36+n*12,*( (n,4 if n<2 else 0,3) if n<4 else (0xffffffff,0,0)))
        original=bytes(uc.mem_read(state,120))
        assert command(seq,last,14,3)[3:5]==(4,0xc16)
        assert bytes(uc.mem_read(state,120))==original and words(meta+31*4,1)==(last,)
        reply=command(seq,last,14,1)
        assert reply[3:7]==(14,0,1,4)
        assert words(state+7*4,1)==(1,) and words(state+36,3)==(0xffffffff,0,0)
        assert all(words(state+36+n*12,3)==(n,4,3) for n in (1,2,3))
        after=bytes(uc.mem_read(state,120))
        assert command(seq,last,14,1)==reply and bytes(uc.mem_read(state,120))==after
        assert command(seq+1,seq,14,4)[3:7]==(14,0,4,4)
        assert command(seq+2,seq+1,14,4)[3:7]==(14,0,4,4)
        cases.append('op14 all-or-nothing release/claim, READY release refusal retains cursor/state, duplicate response replay, release-only and empty exchange')
    if build.get('unrestricted_frequency'):
        cases=[c.replace('foreign-route centers','unrepresentable centers').replace('cross-route B5 raw rejected','unrepresentable Hz rejected').replace('bounded envelopes','unrestricted centers').replace('explicit bounds','unrestricted centers').replace('table edges','legacy table points') for c in cases]
    stop_loop=verify_lossy_stop_loop(directory,build) if build.get('experimental_lossy_scratch') else []
    return dict(status='passed',device_accessed=False,hardware_tested=False,tests=cases,
        lossy_polling_stop_faults=stop_loop,
        memory_layout=dict(data_start=hex(0x80960000),data_end_exclusive=hex(0x80960000+7*slot_bytes),
            next_live_state=hex(stream_address),data_to_state_gap_bytes=stream_address-(0x80960000+7*slot_bytes),
            slots=7,slot_bytes=slot_bytes,resident_free_bytes=0x4000-build['resident']['bytes'],
            conditional_ring_budget_ms={str(bw):7*slot_bytes/(7680000*(1<<min(bw,4)))*1000 for bw in build.get('bandwidth_indices',[0])}),
        elf=elf_path.relative_to(ROOT).as_posix(),elf_sha256=hashlib.sha256(elf_path.read_bytes()).hexdigest(),
        resident_sha256=build['resident']['sha256'],control_sha256=build['control']['sha256'],
        new_ap_mailbox=hex(mailbox),new_generation=hex(generation),
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__),ROOT/'tools/build_capture_bridge.py',ROOT/'firmware/capture/build-recipe.json',ROOT/'firmware/capture/rxcapt_finite_abi.h',
                *[ROOT/'firmware/capture'/name for name in ('rf_terminal_rx.c','rf_terminal_service.c','rf_terminal_control.c','rxcapt_profile.h','rxcapt_profile.c','rxcapt_profile_nv.h',
                    'rxcapt_ring_resident.c','rxcapt_stream_batch.c','rxcapt_stream_publish.c',
                    'rxcapt_rf_core_snapshot.h','rxcapt_rf_phase_log.h')],
                *([ROOT/'firmware/capture/rxcapt_lossy_pair.c',ROOT/'firmware/capture/rxcapt_lossy_pair.h',
                   ROOT/'firmware/capture/rxcapt_stream_idle.h'] if build.get('experimental_lossy_scratch') else []),
                *([ROOT/'firmware/capture/rxcapt_fem_override.h',ROOT/'firmware/rf_rebuild/rf_frontend_override.c',
                   ROOT/'firmware/rf_rebuild/rf_frontend_override.h'] if build.get('experimental_fem_override') else []),
                directory/'build.json',directory/'control.elf']},
        scope='compiled CP mailbox/ring/export functions exercised in ARM emulator; cache/MMU hardware and RF/DMA not validated')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True,help='explicit paired CP build directory; never infer a historical version')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=verify(args.directory)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
