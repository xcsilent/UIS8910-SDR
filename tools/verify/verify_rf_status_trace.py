"""Execute linked CP RF trace, assert fixed reads/no RF writes, decode records."""
import argparse,hashlib,json,struct,sys,types,tempfile
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/host-test-deps'));sys.path.insert(0,str(ROOT/'tools'))
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
from sdr.rf_status import decode,snapshot

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True,help='explicit matching CP build directory')
    parser.add_argument('--output',type=Path,default=ROOT/'records/rf/status-trace-verification.json')
    args=parser.parse_args()
    directory=args.directory.resolve();build=json.loads((directory/'build.json').read_text())
    abi=build['rf_status_trace'].get('abi',1);size={1:256,2:512,3:512,4:512,5:512}[abi]
    assert build['rf_status_trace']['bytes']==size
    slot_bytes=build.get('slot_bytes',8000)
    address=int(build['rf_status_trace']['address'],0)
    assert address==(0x8096e000 if slot_bytes==8192 else 0x8096dc00)
    image=directory/'resident.elf';cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    cpu.mem_map(0x80960000,0x20000);cpu.mem_map(0x50000000,0x40000)
    if abi==4:
        cpu.mem_map(0x804e0000,0x10000);cpu.mem_map(0x25100000,0x3000)
    with image.open('rb') as stream:
        elf=ELFFile(stream)
        for segment in elf.iter_segments():
            if segment['p_type']=='PT_LOAD':cpu.mem_write(segment['p_vaddr'],segment.data())
        entry=next(s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name=='terminal_rf_status_trace')
    reads=[];writes=[]
    def read(cpu,access,address,size,value,context):
        if 0x50000000<=address<0x50040000:reads.append((address,size))
    def write(cpu,access,destination,width,value,context):
        if not (address<=destination and destination+width<=address+size or 0x8097f000<=destination and destination+width<=0x8097f800):
            raise AssertionError('unexpected trace store '+hex(destination))
        writes.append((destination,width,value))
    cpu.hook_add(UC_HOOK_MEM_READ,read);cpu.hook_add(UC_HOOK_MEM_WRITE,write)
    def call(stage):
        cpu.reg_write(UC_ARM_REG_SP,0x8097f700);cpu.reg_write(UC_ARM_REG_LR,0x80970001)
        cpu.reg_write(UC_ARM_REG_R0,stage);cpu.emu_start(entry|1,0x80970000,count=5000)
        assert cpu.reg_read(UC_ARM_REG_PC)==0x80970000
    call(0);assert not reads
    fixtures={0x50030374:0x12b3,0x50030364:0x3456,0x50030410:0x3855,
        0x50032a00:0x9007,0x500302e0:0x1234,0x500302c0:0x5678,
        0x5000b464:1,0x5000b526:7}
    if abi in (2,3,4,5):fixtures.update({0x5003036c:0x0801,0x5000b538:4,0x5000b534:2,
        0x50030468:0x01ea,0x50030480:2,0x5000b4e0:0x1234,0x5000b52a:2,
        0x50030324:0x4000,0x50030354:0x0800})
    if abi in (3,4,5):fixtures.update({0x500096e4:13,0x500096e6:0x9a,0x500096e8:0x96,0x5000a7fa:13})
    for a,v in fixtures.items():cpu.mem_write(a,struct.pack('<H',v))
    if abi in (3,4,5):cpu.mem_write(0x50007e18,struct.pack('<I',0x96b0))
    if abi==5:
        cpu.mem_write(0x500010e8,struct.pack('<I',0x0120506f))
        cpu.mem_write(0x50006118,struct.pack('<2I',17,0x974c))
    command_reads=[]
    if abi==4:
        objects=(0x804ee978,0x804efcc8,0x804edc98,0x804ee4a4,0x804ef320)
        pointers=(0x25101260,0x2510157c,0x25102260,0x2510257c,0x2510257d)
        for obj,pointer in zip(objects,pointers):cpu.mem_write(obj+0x2c,struct.pack('<I',pointer))
        for pointer in pointers[:4]:cpu.mem_write(pointer,struct.pack('<I',pointer^0x12345678))
        def command_read(cpu,access,a,n,v,c):
            if 0x25100000<=a<0x25103000:command_reads.append((a,n))
        cpu.hook_add(UC_HOOK_MEM_READ,command_read)
    cpu.mem_write(0x5000b53c,struct.pack('<I',23307000));cpu.mem_write(0x8097f80c,struct.pack('<I',26))
    for stage,value in enumerate((0,0x800,0xffff,0x7ff,0),1):
        cpu.mem_write(0x5003037c,struct.pack('<H',value));call(stage)
    raw=bytes(cpu.mem_read(address,size));decoded=decode(raw,int(build['generation'],0))
    assert decoded['complete'] and [r['status_bit11'] for r in decoded['records']]==[False,True,True,False,False]
    for r in decoded['records']:
        assert r['configured_divider']==7 and r['context_factor_b526']==7
        assert r['encoding_302e0']==0x1234 and r['encoding_302c0']==0x5678 and r['working_raw']==23307000
        if abi in (2,3,4,5):
            assert r['rx_status_3036c']==0x0801 and r['rxpll_cal_ready_reference'] and r['rxpll_vco_bits_reference']==1
            assert r['selector']==4 and r['rx_port']==2 and r['route_30468']==0x01ea and r['route_30480']==2
            assert r['analog_mode_flag_b4e0']==0x1234 and r['digital_flag_b52a']==2
            assert r['bbpll1_lock_reference'] and not r['bbpll2_lock_reference']
        if abi in (3,4,5):
            saved=r['rffe_saved_result']
            assert saved['target_slave']==saved['configured_target_slave']==13
            assert saved['manufacturer_id_low']==0x9a and saved['product_id']==0x96
            assert saved['config_pointer_matches'] and saved['stable_double_read'] and saved['target_matches_configuration']
            assert not saved['hardware_identity_verified'] and not saved['completion_observed'] and not saved['timeout_known']
    expected=set(fixtures)|{0x5003037c,0x5000b53c}
    if abi in (3,4,5):expected.add(0x50007e18)
    if abi==5:expected.update((0x500010e8,0x50006118,0x5000611c))
    reads_per_stage=len(expected)+(3 if abi in (3,4,5) else 0)+(2 if abi==5 else 0)
    assert len(reads)==5*reads_per_stage and {a for a,n in reads}==expected
    if abi in (3,4,5):
        counts=Counter(a for a,n in reads)
        assert all(counts[a]==(10 if a in (0x500096e4,0x500096e6,0x500096e8) or abi==5 and a in (0x50006118,0x5000611c) else 5) for a in expected)
        assert not any(0x5003c000<=a<0x5003d000 for a,n in reads)
    if abi==4:
        assert command_reads==[(p,4) for p in pointers[:4]]*2
        assert len(decoded['command_observations'])==2
        for row in decoded['command_observations']:
            assert [e['valid'] for e in row['entries']]==[True]*4+[False]
            assert [e['value'] for e in row['entries'][:4]]==[p^0x12345678 for p in pointers[:4]]
    call(5);before=bytes(cpu.mem_read(address,size));read_count=len(reads)
    call(5);assert bytes(cpu.mem_read(address,size))==before and len(reads)==read_count
    rejected=0
    wrong_abi=bytearray(raw);struct.pack_into('<I',wrong_abi,4,2 if abi==1 else 1)
    for data,generation in ((raw[:-1],int(build['generation'],0)),(raw,1),(bytes(size),int(build['generation'],0)),(bytes(wrong_abi),int(build['generation'],0))):
        try:decode(data,generation)
        except ValueError:rejected+=1
        else:raise AssertionError('malformed diagnostic accepted')
    if abi in (2,3,4,5):
        for bits in range(8):
            status_word=(bits<<11)|0x321
            synthetic=bytearray(raw)
            for offset in (8+1,8+8):struct.pack_into('<I',synthetic,offset*4,status_word)
            row=decode(bytes(synthetic),int(build['generation'],0))['records'][0]
            for bank in ('rx','tx'):
                assert row[bank+'pll_cal_ready_reference']==bool(bits&1)
                assert row[bank+'pll_cnt_enable_reference']==bool(bits&2)
                assert row[bank+'pll_cal_enable_reference']==bool(bits&4)
                assert row[bank+'pll_vco_bits_reference']==0x321
        wrong_reserved=bytearray(raw);struct.pack_into('<I',wrong_reserved,(8+(13 if abi==2 else 15))*4,8)
        try:decode(bytes(wrong_reserved),int(build['generation'],0))
        except ValueError:rejected+=1
        else:raise AssertionError('nonzero reserved word accepted')
    if abi in (3,4,5):
        call(0);cpu.mem_write(0x50007e18,struct.pack('<I',0x1234));reads.clear();call(1)
        bad_pointer=decode(bytes(cpu.mem_read(address,size)),int(build['generation'],0))['records'][0]['rffe_saved_result']
        assert not bad_pointer['config_pointer_matches'] and not bad_pointer['stable_double_read']
        assert not any(a in (0x500096e4,0x500096e6,0x500096e8,0x5000a7fa) for a,n in reads)
        cpu.mem_write(0x50007e18,struct.pack('<I',0x96b0))
        call(0);reads.clear()
        def unstable(cpu,access,a,n,v,c):
            if a==0x500096e4 and sum(x==a for x,width in reads)==2:cpu.mem_write(a,struct.pack('<H',14))
        hook=cpu.hook_add(UC_HOOK_MEM_READ,unstable);call(1);cpu.hook_del(hook)
        changed=decode(bytes(cpu.mem_read(address,size)),int(build['generation'],0))['records'][0]['rffe_saved_result']
        assert not changed['stable_double_read'] and not changed['hardware_identity_verified']
        cpu.mem_write(0x500096e4,struct.pack('<H',13))
        for value in (0,0xffff):
            call(0)
            for a in (0x500096e6,0x500096e8):cpu.mem_write(a,struct.pack('<H',value))
            call(1)
            empty=decode(bytes(cpu.mem_read(address,size)),int(build['generation'],0))['records'][0]['rffe_saved_result']
            assert empty['stable_double_read'] and not empty['hardware_identity_verified'] and not empty['timeout_known']
    call(0);reset=decode(bytes(cpu.mem_read(address,size)),int(build['generation'],0))
    assert not reset['records'] and not reset['command_observations']
    if abi==5:
        assert not reset['execution_observations'] and not any(cpu.mem_read(address+352,160))
        for row in decoded['execution_observations']:
            assert row['matching_observer'] and row['stable_double_read']
            assert row['count_before']==row['count_after']==17
            assert row['last_pointer_before']==row['last_pointer_after']=='0x974c'
        cpu.mem_write(0x500010e8,struct.pack('<I',0));reads.clear();call(1)
        skipped=decode(bytes(cpu.mem_read(address,size)),int(build['generation'],0))['execution_observations'][0]
        assert not skipped['matching_observer'] and not any(a in (0x50006118,0x5000611c) for a,n in reads)
        call(0);cpu.mem_write(0x500010e8,struct.pack('<I',0x0120506f));reads.clear()
        def moving(cpu,access,a,n,v,c):
            if a==0x50006118 and sum(x==a for x,width in reads)==2:cpu.mem_write(a,struct.pack('<I',18))
        hook=cpu.hook_add(UC_HOOK_MEM_READ,moving);call(1);cpu.hook_del(hook)
        unstable=decode(bytes(cpu.mem_read(address,size)),int(build['generation'],0))['execution_observations'][0]
        assert unstable['matching_observer'] and not unstable['stable_double_read']
        for index,value in ((88,2),(89,0),(94,1),(95,1),(96,3)):
            malformed=bytearray(raw);struct.pack_into('<I',malformed,index*4,value)
            try:decode(bytes(malformed),int(build['generation'],0))
            except ValueError:rejected+=1
            else:raise AssertionError('malformed execution row accepted')
    if abi==4:
        assert not any(cpu.mem_read(address+88*4,160))
        command_reads.clear();call(1);assert not command_reads
        # Both aligned values outside each window and an unaligned pointer
        # must be skipped by the actual linked ARM code.
        invalid=(0,0x2510125c,0x25101580,0x2510225c,0x25102580)
        for obj,pointer in zip(objects,invalid):cpu.mem_write(obj+0x2c,struct.pack('<I',pointer))
        call(2);call(3);assert not command_reads
        invalid_rows=decode(bytes(cpu.mem_read(address,size)),int(build['generation'],0))['command_observations']
        assert len(invalid_rows)==2 and all(not e['valid'] for r in invalid_rows for e in r['entries'])
        for index,value in ((3,1),(88,0),(108,0),(89,0),(91,2),(104,1)):
            malformed=bytearray(raw);struct.pack_into('<I',malformed,index*4,value)
            try:decode(bytes(malformed),int(build['generation'],0))
            except ValueError:rejected+=1
            else:raise AssertionError('malformed command observation accepted')
    assert 0x80960000+7*slot_bytes<=address and address+size<=0x8096e300
    # A wrong running generation must reject before the candidate DDR address.
    called=[];actual_generation=[int(build['generation'],0)-0x10000]
    class Transport:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    class Client:
        def __init__(self,*args):pass
        def info(self):return dict(firmware='uis8910-sdr-bw0-usb-v1',bulk_read=True,
            cp_baseline_sha256='bd25923aa2fd2cde32fafe59305b6655a79645ad7ff447b74f0ffd4286a020d1')
        def request(self,operation):
            assert operation==44;w=[0]*48
            for i,v in {0:0x31574353,1:1,3:4,5:2,12:3,30:1,37:1}.items():w[i]=v
            return struct.pack('<48I',*w)
        def bulk_read(self,read_address,length,width):
            called.append(read_address)
            if read_address==0x8096fec0:
                return struct.pack('<16I',0x54524d31,actual_generation[0],2,30,*([0]*12))
            assert read_address==address and length==size and width==4;return raw
    previous={name:sys.modules.get(name) for name in ('serial','uis_debug')}
    sys.modules['serial']=types.SimpleNamespace(Serial=lambda *args,**kwargs:Transport())
    sys.modules['uis_debug']=types.SimpleNamespace(Client=Client)
    try:
        with tempfile.TemporaryDirectory(dir=ROOT/'work') as temp:
            rejected_generation=snapshot('COM_TEST',directory/'build.json',Path(temp)/'wrong.json')
            assert rejected_generation['status']=='failed' and not rejected_generation['trace_address_read'] and address not in called
            actual_generation[0]=int(build['generation'],0)
            accepted=snapshot('COM_TEST',directory/'build.json',Path(temp)/'right.json')
            assert accepted['status']=='passed' and accepted['complete'] and accepted['trace_address_read']
    finally:
        for name,old in previous.items():
            if old is None:sys.modules.pop(name,None)
            else:sys.modules[name]=old
    deps=[Path(__file__),image,directory/'build.json',ROOT/'firmware/capture/rxcapt_rf_status_trace.h',
        ROOT/'firmware/capture/rf_terminal_rx.c',ROOT/'tools/sdr/rf_status.py']
    if abi==4:deps.append(ROOT/'firmware/capture/rxcapt_fem_command_snapshot.h')
    report=dict(status='passed',device_accessed=False,hardware_tested=False,
        trace_abi=abi,trace_bytes=size,trace_address=hex(address),slot_bytes=slot_bytes,
        tests=['linked ARM trace initialization, five stages and decoder','exact'+str(reads_per_stage)+'RF/context loads per stage; no RF/DMA/IQ store',
            'fixed capacity ignores further samples','new transaction resets count','generation/length/magic/ABI rejection','DDR trace outside DMA ring/STREAM'],
        host_gate_tests=['mismatched CP generation refuses before trace DDR','matching drained CP reads stable record and decodes'],
        rejected_inputs=rejected,snapshot=decoded,
        fem_tests=(['config pointer mismatch skips extra RAM reads','unstable double read flagged','zero/ffff IDs never prove identity','no RFFE peripheral access'] if abi in (3,4,5) else []),
        command_tests=(['four inclusive window edges read only at stages2/3','unaligned and out-of-window pointers skipped','reset clears both tail rows','stage/count, flags, pointer and reserved corruption rejected','no controller writes'] if abi==4 else []),
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in deps})
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status='passed',RF_reads_per_stage=reads_per_stage,rejected_inputs=rejected)))

if __name__=='__main__':main()
