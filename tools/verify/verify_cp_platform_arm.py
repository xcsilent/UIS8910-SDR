"""Exercise the compiled SDK platform adapter; OS/cache effects are recorded stubs."""
import hashlib
import argparse
import json
from pathlib import Path
import subprocess
import struct
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/host-test-deps'))
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir',type=Path,required=True,help='explicit CP transport build')
    parser.add_argument('--output',type=Path,default=ROOT/'records/usb/cp-platform-arm-verification.json')
    args=parser.parse_args();build=args.build_dir.resolve()
    report=json.loads((build/'build.json').read_text())
    generation=int(report['cp_generation'],0)
    slot_bytes=report.get('slot_bytes',8000)
    obj=ROOT/report['object']
    assert hashlib.sha256(obj.read_bytes()).hexdigest()==report['object_sha256']
    gcc=ROOT/'inputs/repositories/rda8910-csdk-hotelec/prebuilts/win32/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
    hooks={name:0x70000100+i*16 for i,name in enumerate(report['undefined_symbols'])
           if not name.startswith('__aeabi_')}
    elf=build/'platform-test.elf'
    subprocess.run([str(gcc),'-mcpu=cortex-a5','-mthumb','-mfpu=neon-vfpv4','-mfloat-abi=hard',
        '-nostdlib',str(obj),'-lgcc','-Wl,-Ttext=0x60000000,-e,cp_usb_8910_prepare',
        *['-Wl,--defsym='+name+'='+hex(address) for name,address in hooks.items()],'-o',str(elf)],check=True)
    uc=Uc(UC_ARCH_ARM,UC_MODE_ARM)
    uc.mem_map(0x60000000,0x400000)
    uc.mem_map(0x80000000,0x1000000)
    uc.mem_map(0x70000000,0x1000)
    with elf.open('rb') as stream:
        image=ELFFile(stream)
        symbols={s.name:s['st_value'] for s in image.get_section_by_name('.symtab').iter_symbols()}
        for segment in image.iter_segments():
            if segment['p_type']=='PT_LOAD' and segment['p_filesz']:
                uc.mem_write(segment['p_vaddr'],segment.data())
    uc.reg_write(UC_ARM_REG_C1_C0_2,0xf00000)
    uc.reg_write(UC_ARM_REG_FPEXC,0x40000000)
    events=[]
    names={address:name for name,address in hooks.items()}
    names.update({0x70000800:'allocate',0x70000810:'free',0x70000820:'enqueue',
                  0x70000830:'dequeue',0x70000840:'launch'})
    run={'clock':0,'allocated':0,'freed':0,'mode':'refuse','notified':True}
    def put(address,*values):
        uc.mem_write(address,struct.pack('<'+'I'*len(values),*values))
    def stopped():
        put(0x8096fec0,0x54524d31,generation,4,30,0,0,0,0)
        put(0x8096fa40,0x53545231,1,7,1,0,0,0,0)
    def hook(machine,address,size,context):
        if address==0x70000000:
            machine.emu_stop()
        elif address in names:
            name=names[address]
            a,b=machine.reg_read(UC_ARM_REG_R0),machine.reg_read(UC_ARM_REG_R1)
            events.append((name,a,b))
            result=0x80d20000 if name=='osiSemaphoreCreate' else 1
            if name=='memset':
                machine.mem_write(a,bytes([b&255])*machine.reg_read(UC_ARM_REG_R2))
            elif name=='osiSemaphoreTryAcquire':
                assert b==0, 'capture polling must never block for a 20-ms RTOS tick'
                result=int(run['notified'])
            elif name=='osiThreadSleepUS':
                assert a==250
            elif name=='osiUpTimeUS':
                result=run['clock']*1000;machine.reg_write(UC_ARM_REG_R1,0)
            elif name=='osiUpTime':
                run['clock']+=100
                result=run['clock']
                machine.reg_write(UC_ARM_REG_R1,0)
            elif name=='allocate':
                result=0x80d40000+run['allocated']*64
                run['allocated']+=1
            elif name=='free': run['freed']+=1
            elif name=='launch':
                assert run['allocated']==7, 'RF launch preceded request allocation'
                if run['mode']=='refuse': result=0
                elif run['mode']=='uncertain': result=0xffffffff
                elif run['mode']=='ready':
                    put(0x8096fec0,0x54524d31,generation,2,27,0,0,0,0)
                    put(0x8096fa40,0x53545231,1,7,0,0,0,0,0)
            elif name=='osiDCacheClean' and run['mode'] in ('ready','delayed_rearm') and a==int(report['ap_mailbox'],16):
                request=struct.unpack('<8I',machine.mem_read(a,32))
                if request[0]==0x52585331:
                    assert request[3] in (7,9,13)
                    if run['mode']=='delayed_rearm' and request[3]!=13:
                        machine.reg_write(UC_ARM_REG_R0,result)
                        machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR));return
                    put(a+32,request[0],request[1],request[2],request[3],0,request[5],0,request[2])
                    if request[3]==13: run['configured']=request[5]
                    if request[3]==7: stopped()
                    elif request[3]==9:
                        assert run['allocated']==14 and run['freed']==7
                        put(0x8096fec0,0x54524d31,generation,6,27,0,0,0,0)
                        put(0x8096fa40,0x53545231,1,7,0,0,0,0,0)
            machine.reg_write(UC_ARM_REG_R0,result)
            machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR))
    uc.hook_add(UC_HOOK_CODE,hook)
    def call(name,*args):
        for reg,value in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),args):
            uc.reg_write(reg,value)
        uc.reg_write(UC_ARM_REG_SP,0x80eff000)
        if len(args)>4: put(0x80eff000,*args[4:])
        uc.reg_write(UC_ARM_REG_LR,0x70000000)
        uc.emu_start(symbols[name],0,count=100000)
        assert uc.reg_read(UC_ARM_REG_PC)==0x70000000, name+' did not return'
        return uc.reg_read(UC_ARM_REG_R0)
    state=0x80d00000
    mailbox=int(report['ap_mailbox'],16)
    assert call('cp_usb_8910_prepare',state,mailbox)==1
    assert [(n,a,b) for n,a,b in events if n in ('osiDCacheClean','osiDCacheInvalidate')]==[
        ('osiDCacheInvalidate',mailbox+32,32),('osiDCacheClean',mailbox,32)]
    before=len(events)
    assert call('cp_usb_8910_prepare',state,mailbox)==0 and len(events)==before
    for slot in range(7):
        address=0x80960000+slot*slot_bytes
        before=len(events)
        assert call('prepare_tx',state,address,slot_bytes)==1
        assert events[before:]==[('osiDCacheInvalidate',address,slot_bytes)]
    before=len(events)
    for address,length in ((0x80960001,slot_bytes),(0x80960000,slot_bytes-1),(0x80960000+7*slot_bytes,slot_bytes),(0x8095ffe0,slot_bytes)):
        assert call('prepare_tx',state,address,length)==0
    assert len(events)==before
    call('cp_usb_8910_wait',state,100)
    assert events[-1]==('osiSemaphoreTryAcquire',0x80d20000,0)
    run['notified']=False
    before=len(events);call('cp_usb_8910_wait',state,1)
    assert [e for e in events[before:] if e[0]!='osiUpTimeUS']==[('osiSemaphoreTryAcquire',0x80d20000,0),('osiThreadSleepUS',250,0)]
    assert sum(e[0]=='osiUpTimeUS' for e in events[before:])==2
    before=len(events);call('cp_usb_8910_wait',state,0)
    assert events[before:]==[('osiSemaphoreTryAcquire',0x80d20000,0)]
    run['notified']=True
    assert call('cp_usb_8910_dispose',state)==1
    assert events[-1][0]=='osiSemaphoreDelete'
    assert call('cp_usb_8910_dispose',state)==0
    # Execute the actual outer run entry, with a fake asynchronous RF launch.
    # Data producer and bus timing are intentionally absent from this test.
    controller,endpoint,launch=0x80d30000,0x80d31000,0x80d32000
    def run_setup(mode):
        uc.mem_write(state,bytes(0x10000))
        uc.mem_write(mailbox,bytes(64))
        uc.mem_write(0x8096fa40,bytes(128))
        uc.mem_write(0x8096fec0,bytes(32))
        uc.mem_write(controller,bytes(100))
        run.update(clock=0,allocated=0,freed=0,mode=mode)
        put(controller+44,0x70000820)
        put(controller+52,0x70000830)
        put(controller+76,0x70000800,0x70000810)
        uc.mem_write(endpoint,bytes.fromhex('86000002'))
        put(launch,controller,endpoint,mailbox,100,0x70000840,0)
    run_setup('refuse')
    assert call('cp_usb_8910_run',state,launch)==0 and run['freed']==7
    run_setup('uncertain')
    assert call('cp_usb_8910_run',state,launch)==4 and run['freed']==0
    assert call('cp_usb_8910_dispose',state)==0
    stopped(); call('cp_usb_8910_tick',state)
    assert run['freed']==7 and call('cp_usb_8910_dispose',state)==1
    run_setup('timeout')
    assert call('cp_usb_8910_run',state,launch)==4 and run['freed']==0
    assert call('cp_usb_8910_dispose',state)==0
    stopped(); call('cp_usb_8910_tick',state)
    assert run['freed']==7 and call('cp_usb_8910_dispose',state)==1
    run_setup('ready')
    assert call('cp_usb_8910_run',state,launch)==3 and run['freed']==7
    assert call('cp_usb_8910_restart',state,controller,endpoint,100,8816000,20,2526)==3
    assert run['allocated']==run['freed']==14
    assert struct.unpack('<8I',uc.mem_read(mailbox,32))[2]==4
    run['mode']='delayed_rearm'
    assert call('cp_usb_8910_restart',state,controller,endpoint,100,8816000,20,2526)==4
    assert run['allocated']==21 and run['freed']==14
    call('cp_usb_8910_tick',state)
    assert run['freed']==14, 'old STOP must not retire uncertain REARM requests'
    assert call('cp_usb_8910_dispose',state)==0
    for channel,raw in ((1575,18425001),(3625,9425001),(38950,26000000),
                        (300,21100001),(38000,26199000),(38450,18800001),(40640,24960000),
                        (3100,26550000),(5925,8600000),(6075,8750000),(8865,8590000)):
        run_setup('ready')
        assert call('cp_usb_8910_run',state,launch)==3
        assert call('cp_usb_8910_restart',state,controller,endpoint,100,raw,30,channel)==3
        assert run['allocated']==run['freed']==14
        assert run['configured']==channel|(30<<19)
        before=bytes(uc.mem_read(mailbox,64))
        # Explicit rejection must use a foreign range. Expanded B3/B5/B8
        # envelopes intentionally overlap other profiles at some frequencies.
        invalid_anchor=38950 if raw<18843750 else 2525
        assert call('cp_usb_8910_restart',state,controller,endpoint,100,raw,30,invalid_anchor)==3
        assert run['allocated']==14 and bytes(uc.mem_read(mailbox,64))==before
    run_setup('ready')
    assert call('cp_usb_8910_run',state,launch)==3
    bandwidth=max(report.get('bandwidth_indices',[0,1]))
    assert call('cp_usb_8910_restart_bw',state,controller,endpoint,100,8815000,40,2525,bandwidth)==3
    assert run['configured']==2525|(40<<19)|(bandwidth<<16)
    before=bytes(uc.mem_read(mailbox,64))
    assert call('cp_usb_8910_restart_bw',state,controller,endpoint,100,8815000,40,2525,bandwidth+1)==3
    assert run['allocated']==14 and bytes(uc.mem_read(mailbox,64))==before
    # Fresh setup for the original successful disposal check.
    run_setup('ready')
    assert call('cp_usb_8910_run',state,launch)==3
    assert call('cp_usb_8910_dispose',state)==1
    result=dict(status='passed',hardware_tested=False,device_accessed=False,
        test_scope='actual ARM SDK adapter with OS/cache calls recorded; no physical cache/DMA or RF proof',
        checks=['mailbox cache direction and exact 32-byte ranges','duplicate prepare rejected',
            'seven exact DMA slots invalidated without clean','invalid IQ ranges rejected before cache access',
            'pending notification returns immediately; empty notification requests 250-us high-precision sleep; zero wait never sleeps; actual latency unverified','unused platform resource disposal',
            'all UDC requests allocated before RF launch','definitive no-launch releases allocations',
            'uncertain launch/startup timeout retain allocations until late stopped proof',
            'ready launch reaches duration STOP and drain without payload',
            'drained REARM allocates seven requests before command and retains CP cursor',
            'twelve-profile restart carries explicit anchor, preserves fine center, rejects foreign-range anchor without allocations or mailbox mutation',
            'REARM timeout cannot reclaim using preceding epoch STOP'],
        build='records/usb/cp-platform-build.json',object_sha256=report['object_sha256'],
        dependencies={**report['dependencies'],Path(__file__).relative_to(ROOT).as_posix():hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    output=args.output
    output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
