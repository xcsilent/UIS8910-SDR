"""Exercise the linked AP task/control path; CP, OS and UDC are simulated."""
import argparse,hashlib,json,re,struct
from pathlib import Path
from verify_raw_usb_arm import Machine,RETURN,INPUT,OUTPUT,OUTPUT_SIZE,UDC
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_PC,UC_ARM_REG_LR,UC_ARM_REG_SP
from elftools.elf.elffile import ELFFile
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sdr.sample_rate import nominal_rate

ROOT=Path(__file__).resolve().parents[2]
GATE=0x80970000
GEN=0x52550001

class ServiceMachine(Machine):
    def __init__(self,elf,bindings,full_epochs=0,delay_rearm=False,stop_after_config=False,config_time_advance=0,slots=7):
        self.slots=slots;self.scratch_drops=0
        self.task=0;self.cp_commands=[];self.started=False;self.exchange_commands=0;self.pre_selectors=[]
        self.full_epochs=full_epochs;self.source_epochs=0;self.cp_published=0;self.cp_released=0
        self.delay_rearm=delay_rearm
        self.stop_after_config=stop_after_config;self.stop_return=None;self.inject_stop=False
        self.config_time_advance=config_time_advance
        self.keepalive_until=0;self.next_keepalive=0;self.lease_return_sp=None
        super().__init__(elf,bindings)
        with elf.open('rb') as stream:
            source=None
            for symbol in ELFFile(stream).get_section_by_name('.symtab').iter_symbols():
                if symbol['st_info']['type']=='STT_FILE': source=symbol.name
                elif source=='bw0_usb_service.c' and symbol.name in ('worker','phase','request_stop','capture'):
                    self.symbols['bw0_'+symbol.name]=symbol['st_value']
        self.put(GATE,0x31424455,0x80971001,1,1)
    def metadata(self,stopped=False,new_epoch=False):
        if new_epoch:
            self.source_epochs+=1
            self.source_full=self.source_epochs<=self.full_epochs
            self.cp_published=self.slots if self.source_full else 2 if self.full_epochs or self.slots==6 else 0
            self.cp_released=0
        full=getattr(self,'source_full',False)
        stopped=stopped or full
        self.put(0x8096fec0,0x54524d31,GEN,2,30 if stopped else 27,0,0,0,0)
        self.put(0x8096fa40,0x53545231,1,self.slots,3 if full else 1 if stopped else 0,0,0,self.cp_published,self.cp_released)
        for i in range(self.slots):
            self.put(0x8096fa40+36+i*12,i if self.cp_released<=i<self.cp_published else 0xffffffff,
                0,3 if self.cp_released<=i<self.cp_published else 0)
        if self.slots==6:self.put(0x8096fa40+27*4,0,0,self.scratch_drops)
    def cp_poll(self):
        seq=self.word(GATE+64)
        if seq and seq!=self.word(GATE+128):
            op=self.word(GATE+68);arg=self.word(GATE+88)
            if op==3:
                self.put(GATE+16,self.word(GATE+72),self.word(GATE+92))
                self.put(GATE+128,seq,0,0,0); self.cp_commands.append(('activate',0))
            elif op==5 and arg==0x1001:
                self.put(GATE+128,seq,0,4,7);self.put(GATE+256,7)
                self.cp_commands.append(('initialize',arg))
            elif op==2:
                address=self.word(GATE+72);length=self.word(GATE+76)
                assert address in (0x8097f90c,0x8097f924) and length in (12,4)
                self.uc.mem_write(address,bytes(self.uc.mem_read(GATE+256,length)))
                self.put(GATE+128,seq,0,0,0)
            elif op==5 and arg==0x100b and not self.started:
                assert self.allocated==self.slots
                self.started=True;self.metadata(new_epoch=True);self.cp_commands.append(('launch',arg))
                # Launch remains pending in the debug gateway while CP owns RF.
        lines=self.symbols['test_ram']
        if self.word(lines)==0x52585331 and self.word(lines+12) in (7,9,11,12,13,14):
            seq=self.word(lines+8)
            op=self.word(lines+12)
            if seq!=self.word(lines+40):
                if op==9:
                    if self.delay_rearm: return
                    assert self.allocated==self.freed+self.slots
                    assert self.cp_published==self.cp_released
                    self.cp_commands.append(('rearm',seq));self.metadata(new_epoch=True)
                    self.put(0x8097f924,self.word(lines+20))
                elif op==7: self.metadata(stopped=True)
                elif op==14:
                    self.exchange_commands+=1
                    release=self.word(lines+20)
                    assert self.cp_released<=release<=self.cp_published
                    self.cp_released=release
                    self.metadata(stopped=bool(self.word(0x8096fa40+12)&1))
                    self.put(lines+32,0x52585331,GEN,seq,op,0,release,self.cp_published,seq)
                    return
                elif op==11:
                    first=self.word(lines+20)
                    assert first<self.cp_published
                    self.put(lines+32,0x52585331,GEN,seq,op,0,first,self.cp_published,seq)
                    return
                elif op==12:
                    self.cp_released=self.word(lines+20)
                    assert self.cp_released<=self.cp_published
                    self.metadata(stopped=bool(self.word(0x8096fa40+12)&1))
                else:
                    packed=self.word(lines+20)
                    self.put(0x8097f90c,packed&65535,(packed>>16)&7,(packed>>19)&127)
                    self.pre_selectors.append((packed>>26)&7)
                self.put(lines+32,0x52585331,GEN,seq,op,0,self.word(lines+20),self.cp_released if op==12 else 0,seq)
                if op==13 and self.stop_after_config:
                    self.stop_after_config=False;self.inject_stop=True
                if op==13:
                    self.clock+=self.config_time_advance;self.config_time_advance=0
    def hook(self,uc,address,size,context):
        value=None
        if address==0x70000700:
            if self.lease_return_sp is not None:
                assert uc.reg_read(UC_ARM_REG_R0)==0,'keepalive rejected while controller alive'
                uc.reg_write(UC_ARM_REG_SP,self.lease_return_sp);self.lease_return_sp=None
            values,return_pc=self.stop_return;self.stop_return=None
            for register,value in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),values):
                uc.reg_write(register,value)
            uc.reg_write(UC_ARM_REG_LR,return_pc);uc.reg_write(UC_ARM_REG_PC,return_pc);return
        if address==(self.symbols['osiSemaphoreCreate']&~1): value=0x80de0000
        elif address==(self.symbols['iot_os_create_task']&~1):
            self.task=uc.reg_read(UC_ARM_REG_R0);value=1
        elif address in {(self.symbols[n]&~1) for n in ('osiDCacheClean','osiDCacheInvalidate','osiSemaphoreDelete')}:
            value=0
        elif address==(self.symbols['osiUpTimeUS']&~1):
            uc.reg_write(UC_ARM_REG_R1,0);value=self.clock*1000
        elif address==(self.symbols['osiUpTime']&~1):
            self.clock+=200 if self.worker_mode and self.keepalive_until else 1
            self.cp_poll();uc.reg_write(UC_ARM_REG_R1,0);value=self.clock
            if self.worker_mode and self.keepalive_until and self.clock>=self.keepalive_until and self.stop_return is None:
                self.keepalive_until=0;self.inject_stop=True
            if self.inject_stop:
                self.inject_stop=False
                self.stop_return=((value,0,uc.reg_read(UC_ARM_REG_R2),uc.reg_read(UC_ARM_REG_R3)),uc.reg_read(UC_ARM_REG_LR))
                uc.reg_write(UC_ARM_REG_R0,0);uc.reg_write(UC_ARM_REG_LR,0x70000701)
                uc.reg_write(UC_ARM_REG_PC,self.symbols['bw0_request_stop']);return
            if self.worker_mode and self.keepalive_until and self.clock>=self.next_keepalive and self.stop_return is None:
                self.next_keepalive=self.clock+1000
                self.stop_return=((value,0,uc.reg_read(UC_ARM_REG_R2),uc.reg_read(UC_ARM_REG_R3)),uc.reg_read(UC_ARM_REG_LR))
                self.lease_return_sp=uc.reg_read(UC_ARM_REG_SP)
                uc.reg_write(UC_ARM_REG_SP,self.lease_return_sp-16)
                self.put(self.lease_return_sp-16,OUTPUT_SIZE)
                for reg,v in [(UC_ARM_REG_R0,49),(UC_ARM_REG_R1,INPUT),(UC_ARM_REG_R2,0),(UC_ARM_REG_R3,OUTPUT)]:uc.reg_write(reg,v)
                uc.reg_write(UC_ARM_REG_LR,0x70000701);uc.reg_write(UC_ARM_REG_PC,self.symbols['dispatch']);return
        elif self.full_epochs and address==(self.symbols['osiSemaphoreTryAcquire']&~1):
            if self.delay_rearm and self.word(self.symbols['bw0_phase'])==5:
                self.worker_finished=True;uc.emu_stop();return
            self.clock+=1;value=0
        elif address==(self.symbols['osiThreadSleepUS']&~1):
            assert 25<=uc.reg_read(UC_ARM_REG_R0)<=1000
            self.clock+=1;value=0
        elif address==(self.symbols['osiSemaphoreAcquire']&~1):
            if self.worker_mode and self.word(self.symbols['bw0_phase']) in (4,5):
                self.worker_finished=True;uc.emu_stop();return
            value=1
        if value is not None:
            uc.reg_write(UC_ARM_REG_R0,value);uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR));return
        super().hook(uc,address,size,context)
    def install(self):
        assert self.call('sdr_bw0_install',self.symbols['test_ram'],0,
            self.symbols['bw0_prepare'],self.symbols['bw0_launch'])==0
        assert self.task==self.symbols['bw0_worker']
    def control(self,op,payload=b''):
        if payload:self.uc.mem_write(INPUT,payload)
        result=self.call('dispatch',op,INPUT,len(payload),OUTPUT,OUTPUT_SIZE)
        n=self.word(OUTPUT_SIZE)
        return result,bytes(self.uc.mem_read(OUTPUT,n))
    def run(self):
        self.worker_finished=False
        self.worker_mode=True;self.call('bw0_worker',0);self.worker_mode=False
        assert self.worker_finished

def verify_scheduler_policy(elf,bindings,slots):
    m=ServiceMachine(elf,bindings,slots=slots);m.install()
    query=struct.pack('<I',2)
    def policy():
        code,body=m.control(50,query);assert code==0
        words=struct.unpack('<34I',body);assert words[:2]==(0x31484353,2)
        return words
    assert policy()[32:]==(0,0)
    before=m.control(50,query)[1]
    for bad in (b'x',struct.pack('<3I',2,1,0),struct.pack('<3I',2,0,1),struct.pack('<2I',2,0),struct.pack('<I',3)):
        assert m.control(50,bad)[0]!=0 and m.control(50,query)[1]==before
    cases=[]
    minimum=2 if b'"bw0_scheduler_auto_wait_min_bw":2' in elf.read_bytes() else 5
    cases_to_test=[(5,False,100),(0,True,75),(5,True,75),(5,False,100),(0,False,250)]
    cases_to_test.extend((bw,False,100 if bw>=minimum else 250) for bw in (1,2,3,4))
    for bw,manual,wait in cases_to_test:
        if manual:assert m.control(50,struct.pack('<3I',1,75,20))[0]==0
        elif policy()[32]:assert m.control(50,struct.pack('<3I',2,0,0))[0]==0
        assert m.control(47,struct.pack('<5I',2,40,2330000000,40,bw))[0]==0
        assert m.control(45,struct.pack('<4I',1,100,0,0))[0]==0
        queued=policy();assert queued[2:4]==(wait,20 if manual else 0) and queued[32:]==(int(manual),bw)
        for change in (struct.pack('<3I',1,250,0),struct.pack('<3I',2,0,0)):
            assert m.control(50,change)[0]!=0
            assert policy()==queued
        m.run();final=policy()
        assert final[2:4]==queued[2:4] and final[32:]==queued[32:] and final[31]==4
        # Legacy query remains exactly ABI1/128 bytes.
        code,legacy=m.control(50);assert code==0 and len(legacy)==128 and struct.unpack('<32I',legacy)[1]==1
        cases.append(dict(bandwidth=bw,mode='manual' if manual else 'automatic',wait_us=wait,epoch=final[30]))
    return cases


def verify_preload(elf,bindings,cp):
    """Execute linked first-launch loader; CP gateway replies remain modeled."""
    resident=(ROOT/cp['resident']['path']).read_bytes()
    control=(ROOT/cp['control']['path']).read_bytes()
    package=json.loads((ROOT/cp['control']['package']).read_text())
    cases=[]
    for kind in ('valid','resident_oversize','resident_empty','control_oversize',
                 'control_empty','bad_entry','gateway_busy','gateway_abi'):
        m=ServiceMachine(elf,bindings,slots=6 if cp.get('experimental_lossy_scratch') else 7)
        source,control_source=0x80d40000,0x80d50000
        m.uc.mem_write(source,resident);m.uc.mem_write(control_source,control)
        m.uc.mem_write(0x8097b000,b'\xa5'*0x5000)
        m.uc.mem_write(0x80975000,b'\x5a'*0x2000)
        m.put(GATE+16,0)
        if kind=='gateway_busy':m.put(GATE+16,0x80971001)
        if kind=='gateway_abi':m.put(GATE+8,2)
        n=0x4001 if kind=='resident_oversize' else 0 if kind=='resident_empty' else len(resident)
        c=0x2001 if kind=='control_oversize' else 0 if kind=='control_empty' else len(control)
        entry=0 if kind=='bad_entry' else package['entry_offset']
        result=m.call('bw0_prepare',0,source,n,control_source,c,entry,GEN,38950,40,23300000,0)
        if kind=='valid':
            assert result==0 and m.cp_commands==[('activate',0),('initialize',0x1001)]
            assert bytes(m.uc.mem_read(0x8097b000,len(resident)))==resident
            assert bytes(m.uc.mem_read(0x80975000,len(control)))==control
            assert bytes(m.uc.mem_read(0x8097b000+len(resident),0x4000-len(resident)))==b'\xa5'*(0x4000-len(resident))
            assert bytes(m.uc.mem_read(0x8097f000,0x800))==b'\xa5'*0x800
            assert bytes(m.uc.mem_read(0x80975000+len(control),0x2000-len(control)))==b'\x5a'*(0x2000-len(control))
            assert tuple(m.word(a) for a in (0x8097f90c,0x8097f910,0x8097f914,0x8097f924))==(38950,0,40,23300000)
        else:
            assert result!=0 and not m.cp_commands
            assert bytes(m.uc.mem_read(0x8097b000,0x5000))==b'\xa5'*0x5000
            assert bytes(m.uc.mem_read(0x80975000,0x2000))==b'\x5a'*0x2000
        cases.append(dict(case=kind,result=result))
    return dict(resident_bytes=len(resident),limit_bytes=0x4000,headroom_bytes=0x4000-len(resident),
        cases=cases,scope='Linked AP copy/range/gateway guards and configuration executed; CP initialize/permission/CRC/cache/physical launch are modeled, not verified here.')

def main():
    global GEN
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir',type=Path,required=True,help='explicit AP build directory')
    parser.add_argument('--output',type=Path,default=ROOT/'records/usb/bw0-service-arm-verification.json')
    args=parser.parse_args()
    BUILD=args.build_dir.resolve()
    manifest=BUILD/'appimg-build.json'
    if not manifest.is_file():
        manifest=BUILD/'build.json'
    build=json.loads(manifest.read_text())
    build.setdefault('dependencies',build.get('source_sha256',{}))
    cp_for_test=json.loads((ROOT/build['cp_modules']).read_text())
    slot_bytes=cp_for_test.get('slot_bytes',8000)
    GEN=int(cp_for_test['generation'],0)
    elf=ROOT/build['elf']
    bindings={n:int(v,16) for n,v in re.findall(r'#define SDR_ADDR_(\w+) (0x[0-9a-f]+)u',
        (BUILD/'generated/udc_bindings.h').read_text())}
    preload=verify_preload(elf,bindings,cp_for_test)
    b3_cases=[]
    if cp_for_test.get('unrestricted_frequency'):
        probe=ServiceMachine(elf,bindings,slots=6 if cp_for_test.get('experimental_lossy_scratch') else 7);probe.install()
        for band in cp_for_test['rf_profiles']:
            for hz in (100,1000000000,1447000000,1650000000,3000000000,4294967200):
                code,_=probe.control(47,struct.pack('<5I',2,band,hz,40,0))
                # CONFIG can still reject missing runtime NV; modeled NV includes all retained routes.
                assert code==0,(band,hz,code)
                b3_cases.append(dict(band=band,frequency_hz=hz,accepted=True))
    if cp_for_test.get('experimental_b3_min_hz') is not None:
        floor=cp_for_test['experimental_b3_min_hz']
        probe=ServiceMachine(elf,bindings,slots=6 if cp_for_test.get('experimental_lossy_scratch') else 7);probe.install()
        for hz,accepted in ((floor-100,False),(floor,True),(floor+100,True),(1680000000,True),
                            (1709999900,True),(1710000000,True),(1920000100,False),(floor+1,False)):
            code,_=probe.control(47,struct.pack('<5I',2,3,hz,40,0))
            assert (code==0)==accepted,(hz,code,accepted)
            b3_cases.append(dict(frequency_hz=hz,accepted=accepted))
    scheduler_policy=verify_scheduler_policy(elf,bindings,6 if cp_for_test.get('experimental_lossy_scratch') else 7) if b'"bw0_scheduler_policy_abi":2' in elf.read_bytes() else []
    if cp_for_test.get('experimental_lossy_scratch'):
        m=ServiceMachine(elf,bindings,slots=6);m.install()
        assert b'"bw0_scratch_drops_operation":52' in elf.read_bytes()
        queue_capable=b'"bw0_queue_profile_abi":1' in elf.read_bytes()
        refill_capable=b'"bw0_refill_profile_abi":1' in elf.read_bytes()
        if queue_capable:
            code,body=m.control(51,struct.pack('<I',2));words=struct.unpack('<16I',body)
            assert code==0 and words[:5]==(0x31515055,1,0,0,0)
            if refill_capable:
                code,body=m.control(51,struct.pack('<I',3));refill=struct.unpack('<202I',body)
                assert code==0 and refill[:10]==(0x31524655,1,0,0,0,0,0,0,0,0) and not any(refill[10:])
                assert m.control(51,struct.pack('<I',4))[0]!=0
            else:assert m.control(51,struct.pack('<I',3))[0]!=0
            assert m.control(51,struct.pack('<2I',1,1))[0]==0
        assert m.control(52)[0]!=0
        results=[]
        for epoch,drops,bw,hz in ((1,37,5,2000000000),(2,0xffffffff,0,2330000000),(3,0,1,2330100000)):
            assert m.control(47,struct.pack('<5I',2,40,hz,40,bw))[0]==0
            m.scratch_drops=drops
            assert m.control(45,struct.pack('<4I',1,100,0,0))[0]==0
            assert m.control(52)[0]!=0 # no stale final value while queued
            m.run()
            status=struct.unpack('<48I',m.control(44)[1])
            assert status[3]==4 and status[4]==0 and status[5]==epoch and status[22]==2*slot_bytes
            if queue_capable:
                code,body=m.control(51,struct.pack('<I',2));words=struct.unpack('<16I',body)
                assert code==0 and words[:5]==(0x31515055,1,1,epoch,4)
                assert words[5]==0 and words[8]>=2 and words[7]==0
                if refill_capable:
                    code,body=m.control(51,struct.pack('<I',3));refill=struct.unpack('<202I',body)
                    assert code==0 and refill[:5]==(0x31524655,1,1,epoch,4)
                    assert refill[5:10]==(0,0,0,0,0) # simulated UDC completes synchronously
                    assert m.control(51,b'')[1][-8:]==bytes(8) # old ABI reserved words intact
            assert m.allocated==m.freed==6*epoch
            code,body=m.control(52)
            assert code==0 and struct.unpack('<4I',body)==(0x31504453,1,epoch,drops)
            assert m.control(52,b'x')[0]!=0 and m.control(52)[1]==body
            # Even after AP drain, active scratch or changed CP identity must
            # invalidate the final snapshot rather than return stale counters.
            m.put(0x8096fa40+28*4,1);assert m.control(52)[0]!=0
            m.put(0x8096fa40+28*4,0)
            m.put(0x8096fec0+4,GEN^1);assert m.control(52)[0]!=0
            m.put(0x8096fec0+4,GEN);assert m.control(52)[1]==body
            results.append(dict(epoch=epoch,bandwidth_index=bw,frequency_hz=hz,whole_dropped_pairs=drops,
                                delivered_bytes=status[22],requests_freed=m.freed))
        assert [n for n,a in m.cp_commands]==['activate','initialize','launch','rearm','rearm']
        fem_cases=[]
        if cp_for_test.get('experimental_fem_override'):
            assert b'"bw0_fem_override_operation":53' in elf.read_bytes()
            f=ServiceMachine(elf,bindings,slots=6);f.install()
            def fem(mode=None):
                return f.control(53,b'' if mode is None else struct.pack('<2I',1,mode))
            assert fem()[0]==0 and struct.unpack('<4I',fem()[1])[2]==0
            assert fem(1)[0]!=0 # no first-launch diagnostic override
            assert f.control(47,struct.pack('<5I',2,5,900000000,40,0))[0]==0
            assert f.control(45,struct.pack('<4I',1,100,0,0))[0]==0
            assert fem(1)[0]!=0 # queued is not drained
            f.run()
            for mode in (1,2,0):
                assert fem(mode)[0]==0 and struct.unpack('<4I',fem()[1])[2]==mode
                before=fem()[1]
                assert fem(3)[0]!=0 and fem()[1]==before
                assert f.control(53,b'x')[0]!=0 and fem()[1]==before
                if mode:
                    assert f.control(47,struct.pack('<5I',2,40,2330000000,40,0))[0]!=0
                assert f.control(45,struct.pack('<4I',1,100,0,0))[0]==0
                assert fem(2)[0]!=0
                f.run()
                assert f.pre_selectors[-1]==mode # actual AP packs op13 bits27:26
                w=struct.unpack('<48I',f.control(44)[1]);assert w[3]==4 and w[4]==0
                fem_cases.append(dict(mode=mode,packed_mode=f.pre_selectors[-1],epoch=w[5]))
            assert f.control(47,struct.pack('<5I',2,40,2330000000,40,0))[0]==0
            assert f.allocated==f.freed==24
        paths=[Path(__file__),ROOT/'tools/verify/verify_raw_usb_arm.py',ROOT/build['cp_modules'],elf,
            ROOT/cp_for_test['resident']['path'],ROOT/cp_for_test['control']['path'],ROOT/cp_for_test['control']['package']]
        report=dict(status='passed',device_accessed=False,hardware_tested=False,
            elf=build['elf'],elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
            scope='Linked six-slot AP worker/control operation52 with modeled CP producer and synchronous UDC. Three timed sessions drain two slots each; queued rejection, saturation, generation and active scratch guards. No physical DMA/cache/RF/USB proof.',
            sessions=results,frequency_request_cases=b3_cases,scheduler_policy=scheduler_policy,fem_override_cases=fem_cases,preload=preload,dependencies={**build['dependencies'],**{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}})
        args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return
    m=ServiceMachine(elf,bindings);m.install()
    if b'bw0_segment_profile_operation' in elf.read_bytes():
        m=ServiceMachine(elf,bindings,full_epochs=1);m.install()
        code,body=m.control(51);words=struct.unpack('<40I',body)
        assert code==0 and words[:3]==(0x31525055,1,0)
        assert m.control(51,struct.pack('<2I',1,2))[0]!=0 and m.control(51)[1]==body
        assert m.control(51,b'x')[0]!=0
        assert m.control(51,struct.pack('<2I',1,1))[0]==0
        assert m.control(45,struct.pack('<4I',1,1000,0,0))[0]==0
        assert m.control(51,struct.pack('<2I',1,0))[0]!=0
        m.run();words=struct.unpack('<40I',m.control(51)[1])
        assert words[2]==1 and words[6]>0 and words[16]==words[26]==words[6] and words[36:38]==(1,4)
        assert all(sum(words[10+10*i:16+10*i])==words[6+10*i] for i in range(3))
        assert m.control(51,struct.pack('<2I',1,0))[0]==0
        assert m.control(45,struct.pack('<4I',1,100,0,0))[0]==0
        m.run();words=struct.unpack('<40I',m.control(51)[1]);assert not words[2] and not words[6] and words[36:38]==(2,4)
        m=ServiceMachine(elf,bindings);m.install()
    if b'bw0_scheduler_operation' in elf.read_bytes():
        code,body=m.control(50);words=struct.unpack('<32I',body)
        assert code==0 and words[:4]==(0x31484353,1,250,0) and words[29:]==(8,0,0)
        for wait,burst in ((0,0),(24,0),(1001,0),(50,51)):
            assert m.control(50,struct.pack('<3I',1,wait,burst))[0]!=0
            assert m.control(50)[1]==body
        assert m.control(50,b'x')[0]!=0
        assert m.control(50,struct.pack('<3I',1,50,40))[0]==0
        assert m.control(45,struct.pack('<4I',1,100,0,0))[0]==0
        assert m.control(50,struct.pack('<3I',1,250,0))[0]!=0
        m.run()
        code,body=m.control(50);words=struct.unpack('<32I',body)
        assert code==0 and words[2:4]==(50,40) and words[4]>0 and words[30:]==(1,4)
        assert sum(words[17:23])==words[6] and sum(words[23:29])==words[13]
        assert m.control(50,struct.pack('<3I',1,250,0))[0]==0
        assert m.control(45,struct.pack('<4I',1,100,0,0))[0]==0
        m.run()
        words=struct.unpack('<32I',m.control(50)[1]);assert words[30:]==(2,4) and words[2:4]==(250,0)
        m=ServiceMachine(elf,bindings);m.install()
    for band,hz,gain in ((3,881500000,40),(5,881500001,40),(5,881500000,125),
                        (40,1884374900,40),(40,2790625100,40),(40,881500000,40),(5,2330000000,40),
                        (1,0,40),(38,0,40),(39,0,40),(41,0,40),
                        (34,2009999900,40),(34,2024900100,40),(34,2017500001,40),
                        (7,2619999900,40),(7,2689900100,40),(18,859999900,40),(18,874900100,40),
                        (19,874999900,40),(19,889900100,40),(26,858999900,40),(26,893900100,40),
                        (7,0,40),(18,0,40),(19,0,40),(26,0,40)):
        assert m.control(47,struct.pack('<4I',1,band,hz,gain))[0]!=0
    if 34 not in cp_for_test['rf_profiles']:
        assert m.control(47,struct.pack('<4I',1,34,2017500000,40))[0]!=0
    else:
        assert b'"bw0_rf_profiles":'+json.dumps(cp_for_test['rf_profiles'],separators=(',',':')).encode() in elf.read_bytes()
    assert m.control(47,struct.pack('<4I',1,5,881600000,20))[0]==0
    assert m.control(45,struct.pack('<4I',1,100,0,0))[0]==0
    assert m.control(3,b'')[0]==5 # monitor write blocked before mutation
    assert m.control(21,struct.pack('<I',0x1001))[0]==5 # no competing CP call
    assert m.control(41,struct.pack('<4I',1,100,512,2))[0]==5 # endpoint exclusive
    assert m.control(47,struct.pack('<4I',1,5,882000000,60))[0]==5
    m.run()
    status,payload=m.control(44)
    words=struct.unpack('<48I',payload)
    assert status==0 and words[3]==4 and words[4]==0 and words[15]==1
    assert words[30]==1 and m.allocated==m.freed==7
    assert [name for name,arg in m.cp_commands]==['activate','initialize','launch']
    assert m.word(0x8097f90c)==2526 and m.word(0x8097f914)==20 and m.word(0x8097f924)==8816000
    assert m.word(GATE+64)!=m.word(GATE+128) # held CP is never presented as returned
    assert m.control(47,struct.pack('<4I',1,40,2000000000,60))[0]==0
    assert m.control(45,struct.pack('<4I',1,100,0,0))[0]==0
    m.run()
    words=struct.unpack('<48I',m.control(44)[1])
    assert words[3]==4 and words[4]==0 and words[5]==2 and words[15]==1
    assert words[30]==1 and m.allocated==m.freed==14
    assert words[40]>>8==40 and words[45]==60 and words[47]==2000000000
    assert m.word(0x8097f90c)==38950 and m.word(0x8097f914)==60 and m.word(0x8097f924)==20000000
    assert [name for name,arg in m.cp_commands]==['activate','initialize','launch','rearm']
    assert m.word(GATE+64)!=m.word(GATE+128)
    assert m.control(45,struct.pack('<4I',1,100,0,0))[0]==0
    assert m.control(46)[0]==0; m.run()
    assert len(m.cp_commands)==4 # cancelling queued restart retains drained native CP
    assert m.control(47,struct.pack('<4I',1,5,882000000,30))[0]==0
    assert m.control(45,struct.pack('<4I',1,100,0,0))[0]==0
    m.run()
    words=struct.unpack('<48I',m.control(44)[1])
    assert words[3]==4 and words[5]==4 and m.allocated==m.freed==21
    assert words[40]>>8==5 and m.word(0x8097f90c)==2530 and m.word(0x8097f924)==8820000
    assert [name for name,arg in m.cp_commands]==['activate','initialize','launch','rearm','rearm']
    cp_manifest=ROOT/build['cp_modules']
    cp=json.loads(cp_manifest.read_text())
    assert bytes(m.uc.mem_read(0x8097b000,cp['resident']['bytes']))==(ROOT/cp['resident']['path']).read_bytes()
    assert bytes(m.uc.mem_read(0x80975000,cp['control']['bytes']))==(ROOT/cp['control']['path']).read_bytes()
    m=ServiceMachine(elf,bindings);m.install()
    assert m.control(47,struct.pack('<4I',1,40,2600000000,40))[0]==0
    assert m.control(45,struct.pack('<4I',1,100,0,0))[0]==0
    m.run()
    assert m.word(0x8097f90c)==38950 and m.word(0x8097f924)==26000000
    route_pairs=[
        ((3,1842500100,1575,18425001),(8,942500100,3625,9425001)),
        ((8,942500000,3625,9425000),(40,2330000000,38950,23300000)),
        ((40,2000000000,38950,20000000),(3,1805000000,1200,18050000)),
        ((1,2110000100,300,21100001),(38,2619900000,38000,26199000)),
        ((38,2570000000,38000,25700000),(39,1880000100,38450,18800001)),
        ((39,1919900000,38450,19199000),(41,2496000000,40640,24960000)),
        ((41,2689900000,40640,26899000),(40,2330000000,38950,23300000)),
        ((7,2655000000,3100,26550000),(40,2655000000,38950,26550000)),
        ((18,870000000,5925,8700000),(5,870000000,2410,8700000)),
        ((5,881500000,2525,8815000),(19,881500000,6075,8815000)),
        ((19,881500000,6075,8815000),(26,881500000,8865,8815000))]
    if 34 in cp_for_test['rf_profiles']:
        route_pairs += [((34,2010000000,36275,20100000),(40,2017500000,38950,20175000)),
            ((40,2017500000,38950,20175000),(34,2024900000,36275,20249000)),
            ((34,2017500100,36275,20175001),(5,881500000,2525,8815000))]
        route_pairs += [((5,824000000,2400,8240000),(8,880000000,3450,8800000)),
            ((5,500000000,2400,5000000),(5,700000000,2400,7000000)),
            ((8,1000000000,3799,10000000),(5,925000000,2649,9250000)),
            ((3,1710000000,1200,17100000),(3,1920000000,1949,19200000))]
    for first,second in route_pairs:
        m=ServiceMachine(elf,bindings);m.install()
        for index,(band,hz,channel,raw) in enumerate((first,second)):
            assert m.control(47,struct.pack('<4I',1,band,hz,30+index))[0]==0
            assert m.control(45,struct.pack('<4I',1,100,0,0))[0]==0
            m.run()
            words=struct.unpack('<48I',m.control(44)[1])
            assert words[3]==4 and not words[4] and words[40]>>8==band
            assert words[45]==30+index and words[47]==hz
            assert m.word(0x8097f90c)==channel and m.word(0x8097f914)==30+index
            assert m.word(0x8097f924)==raw and m.allocated==m.freed==7*(index+1)
        assert [name for name,arg in m.cp_commands]==['activate','initialize','launch','rearm']
    m=ServiceMachine(elf,bindings);m.install()
    assert m.control(45,struct.pack('<4I',1,100,0,0))[0]==0
    assert m.control(46)[0]==0;m.run()
    assert not m.cp_commands and m.control(44)[1][15*4:16*4]==bytes(4)
    # Two seven-slot full epochs plus two blocks from the recovered epoch.
    # The initial producer is already FULL before AP's first open attempt.
    m=ServiceMachine(elf,bindings,full_epochs=2);m.install()
    assert m.control(45,struct.pack('<4I',1,1000,0,0))[0]==0
    m.run()
    words=struct.unpack('<48I',m.control(44)[1])
    recovery=struct.unpack('<24I',m.control(48)[1])
    assert words[3]==4 and not words[4] and words[46]>=1000
    assert words[17]==16 and words[22]==16*slot_bytes and words[23]==0
    assert words[24]==words[25]==16 and m.allocated==m.freed==21
    assert recovery[:8]==(0x31524353,1,1,3,2,2,2,0)
    assert recovery[8]>0 and recovery[10]>0 and recovery[11]>=recovery[10]
    assert recovery[13]>=1000 and recovery[16:18]==(1,0)
    assert [name for name,arg in m.cp_commands]==['activate','initialize','launch','rearm','rearm']
    assert m.control(47,struct.pack('<4I',1,8,942500000,20))[0]==0
    assert m.control(45,struct.pack('<4I',1,100,0,0))[0]==0
    m.run()
    words=struct.unpack('<48I',m.control(44)[1]);recovery=struct.unpack('<24I',m.control(48)[1])
    assert words[22]==2*slot_bytes and recovery[2:8]==(2,1,0,0,0,0)
    assert words[40]>>8==8 and words[47]==942500000
    # STOP arrives after CONFIG ACK, before RF REARM: reservations are freed.
    m=ServiceMachine(elf,bindings,full_epochs=1,stop_after_config=True);m.install()
    assert m.control(45,struct.pack('<4I',1,1000,0,0))[0]==0
    m.run()
    words=struct.unpack('<48I',m.control(44)[1]);recovery=struct.unpack('<24I',m.control(48)[1])
    assert words[3]==4 and not words[4] and words[22]==7*slot_bytes
    assert m.allocated==m.freed==14 and recovery[4:8]==(1,1,0,0) and recovery[20]==1
    assert [name for name,arg in m.cp_commands]==['activate','initialize','launch']
    # A missing REARM ACK must retain new USB reservations despite old FULL.
    m=ServiceMachine(elf,bindings,full_epochs=1,config_time_advance=1000);m.install()
    assert m.control(45,struct.pack('<4I',1,1000,0,0))[0]==0
    m.run()
    words=struct.unpack('<48I',m.control(44)[1]);recovery=struct.unpack('<24I',m.control(48)[1])
    assert words[3]==4 and not words[4] and words[46]>=1000
    assert m.allocated==m.freed==14 and recovery[20]==1 and recovery[6]==0
    assert [name for name,arg in m.cp_commands]==['activate','initialize','launch']
    m=ServiceMachine(elf,bindings,full_epochs=1,delay_rearm=True);m.install()
    assert m.control(45,struct.pack('<4I',1,1000,0,0))[0]==0
    m.run()
    words=struct.unpack('<48I',m.control(44)[1]);recovery=struct.unpack('<24I',m.control(48)[1])
    assert words[3]==5 and words[4] and words[22]==7*slot_bytes
    assert words[26] and m.allocated==14 and m.freed==7 and recovery[7]==1
    for bw in build.get('bandwidth_indices',[])[1:]:
        expected=b'bw0_bandwidth_indices":'+json.dumps(build['bandwidth_indices'],separators=(',',':')).encode()
        assert expected in elf.read_bytes()
        m=ServiceMachine(elf,bindings,full_epochs=1);m.install()
        before=m.control(44)[1]
        invalid_bw=8 if build.get('experimental_pre_switch') else max(build['bandwidth_indices'])+1
        assert m.control(47,struct.pack('<5I',2,5,881500000,40,invalid_bw))[0]!=0
        assert m.control(44)[1]==before
        assert m.control(47,struct.pack('<5I',2,5,881500000,40,bw))[0]==0
        words=struct.unpack('<48I',m.control(44)[1])
        rate=0 if bw==5 and (build.get('experimental_bw5_pre_selector') is not None or build.get('experimental_pre_switch')) else nominal_rate(bw)
        assert (words[40]>>4)&7==bw and words[9]==rate
        assert m.control(45,struct.pack('<4I',1,1000,0,0))[0]==0
        m.run()
        assert m.word(0x8097f910)==bw
        if build.get('combined_exchange_supported'):assert m.exchange_commands>0
        assert [name for name,arg in m.cp_commands]==['activate','initialize','launch','rearm']
        assert struct.unpack('<24I',m.control(48)[1])[6]==1
        # The legacy16-byte request intentionally restores default BW0.
        assert m.control(47,struct.pack('<4I',1,5,881600000,20))[0]==0
        assert m.control(45,struct.pack('<4I',1,100,0,0))[0]==0
        m.run()
        words=struct.unpack('<48I',m.control(44)[1])
        assert (words[40]>>4)&7==0 and words[9]==1920000 and m.word(0x8097f910)==0
    if build.get('experimental_pre_switch'):
        assert b'bw0_experimental_pre_selectors\":[5,6,7]' in elf.read_bytes()
        for selector in (6,7,5):
            m=ServiceMachine(elf,bindings);m.install()
            if selector>5:
                assert m.control(47,struct.pack('<5I',2,40,2000000000,40,selector))[0]==0
                assert m.control(45,struct.pack('<4I',1,500,0,0))[0]!=0
            assert m.control(47,struct.pack('<5I',2,40,2000000000,40,1))[0]==0
            assert m.control(45,struct.pack('<4I',1,500,0,0))[0]==0;m.run()
            assert m.control(47,struct.pack('<5I',2,40,2000000000,40,selector))[0]==0
            w=struct.unpack('<48I',m.control(44)[1]);assert (w[40]>>4)&7==selector and w[9]==0
            assert m.control(45,struct.pack('<4I',1,2001,0,0))[0]!=0
            assert m.control(45,struct.pack('<4I',1,500,0,0))[0]==0;m.run()
            assert m.word(0x8097f910)==5 and m.pre_selectors[-1]==selector
            assert struct.unpack('<48I',m.control(44)[1])[3]==4
    if build.get('until_stop_supported'):
        assert b'bw0_until_stop\":true' in elf.read_bytes()
        m=ServiceMachine(elf,bindings,full_epochs=1);m.install()
        assert m.control(49)[0]!=0
        assert m.control(45,struct.pack('<4I',1,0,0,0))[0]==0
        assert m.control(49,b'x')[0]!=0 and m.control(49)[0]==0
        m.keepalive_until=210000;m.run()
        w=struct.unpack('<48I',m.control(44)[1]);rec=struct.unpack('<24I',m.control(48)[1])
        assert w[3]==4 and w[6]==0 and w[46]>200000 and rec[21]==0 and rec[22]==1,(w,rec,m.clock,m.cp_commands)
        assert rec[4]==1 and rec[6]==1 and m.allocated==m.freed
        assert m.control(49)[0]!=0
        m=ServiceMachine(elf,bindings);m.install()
        assert m.control(45,struct.pack('<4I',1,0,0,0))[0]==0
        m.run()
        w=struct.unpack('<48I',m.control(44)[1]);rec=struct.unpack('<24I',m.control(48)[1])
        assert w[3]==4 and rec[21]==1 and m.allocated==m.freed and m.control(49)[0]!=0
    report=dict(status='passed',device_accessed=False,hardware_tested=False,
        scope='actual linked AP worker, monitor lock and endpoint arbitration; fake CP metadata/mailbox and synchronous UDC completion, no RF or physical DMA/USB throughput proof',
        checks=['48-word separate control status','monitor mutation/CP call exclusion',
            'if scheduler advertised: operation50 query/config defaults and bounds, queued rejection, drained policy changes, per-START counters and final histograms',
            'fixed-source endpoint exclusion','native control blob/resident preload',
            'activate then initialize then launch','seven UDC requests precede launch',
            'empty producer STOP/drain preserves held CP','second capture uses REARM with fresh USB requests and retained CP cursor',
            'B5 frequency/gain initial writes and drained CONFIG before REARM; invalid or live changes rejected',
            'B40 first launch at 2.6 GHz; B5 to B40 2 GHz to B5 restart routes, raw centers and status preserved',
            'B3/B8 first launch and B3 to B8, B8 to B40, B40 to B3 stopped reconfiguration; fine raw centers and gain preserved',
            'B1/B38/B39/B41 first launches and cross-route REARM preserve fixed anchor, raw center, gain, status and request cleanup',
            'B7 to B40 and overlapping B18 to B5 to B19 to B26 at unchanged Hz keep explicit native anchors and profile status',
            'if B34 advertised: lower/upper and100Hz center first-launch/REARM, cross-route B34/B40/B5 preserve36275 anchor and status',
            'FULL before initial AP open drains, then two automatic recoveries accumulate 16 blocks/'+str(16*slot_bytes)+' bytes in one timed session',
            'recovery observation gaps reported; next user START resets cumulative counters',
            'STOP after CONFIG ACK cancels REARM and releases all new reservations',
            'session deadline expiring during CONFIG cancels REARM rather than starting RF for another duration',
            'uncertain recovery retains new requests and reports pending gap instead of borrowing prior FULL stop proof',
            'queued cancellation skips RF launch',
            'each advertised nonzero BW: ABI2 bounds, first launch, full-ring recovery and legacy BW0 reconfiguration preserve selected BW',
            'if until-STOP advertised: actual op49 renews through simulated210s and full recovery, explicit STOP drains; absent keepalive expires and cannot revive a stopped lease'],
        elf=build['elf'],elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
        dependencies={**build['dependencies'],**{
            p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path(__file__),ROOT/'tools/verify/verify_raw_usb_arm.py',cp_manifest,
             ROOT/cp['resident']['path'],ROOT/cp['control']['path'],ROOT/build['appimg'],
             BUILD/'generated/bw0_service_blob.h',BUILD/'generated/cp_transport_binding.h']}})
    path=args.output
    path.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
