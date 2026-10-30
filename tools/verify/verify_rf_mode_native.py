"""Bounded execution of original RF mode helper, no device access.

Standard RV32 instructions execute in Unicorn. Only the seven legacy PULP
operations required by this slice are modeled from pinned local references.
This is not a model of analog hardware or evidence that mode equals BW index.
"""
import hashlib,json,re,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/host-test-deps'))
sys.path.insert(0,str(ROOT/'tools'))
from sdr.rf_catalog import catalog,INPUTS as CATALOG_INPUTS
from unicorn import Uc,UC_ARCH_RISCV,UC_MODE_RISCV32,UC_HOOK_MEM_WRITE,UC_ARCH_ARM,UC_MODE_ARM
from unicorn import riscv_const as registers
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_SP,UC_ARM_REG_PC
from elftools.elf.elffile import ELFFile
X=[getattr(registers,'UC_RISCV_REG_X'+str(i)) for i in range(32)]
PC=registers.UC_RISCV_REG_PC
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def signed(v,n):return v-(1<<n) if v&(1<<(n-1)) else v
def bandwidth_chain(image,encodings,cp,axf):
    blob=cp.read_bytes();base=0x801ab000
    with axf.open('rb') as f:
        elf=ELFFile(f)
        symbol=next(s for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name=='xcvr_rxon')
        section=elf.get_section(symbol['st_shndx']);at=(symbol['st_value']&~1)-section['sh_addr']
        prefix=section.data()[at:at+46]
    # RXON and RXON-nodci have the same packing prefix, different later gain helpers.
    offsets=[];at=blob.find(prefix)
    while at>=0: offsets.append(at);at=blob.find(prefix,at+1)
    assert len(offsets)==2
    for at in offsets:
        assert struct.unpack_from('<3I',blob,at+60)==(0x804ed5ac,0x804ed5f8,0x804f42b8)
    route_report=json.loads((ROOT/'records/usb/rf-channel-routes.json').read_text())
    routes=route_report['rows']
    profiles={r['raw_band_id'] for r in catalog()['rows'] if r['software_integrated']}
    cases=[]
    for route in routes:
        if route['raw_band_id'] not in profiles: continue
        observation=route['observations'][0]
        fixture='SDK default NV route'
        if observation['nv_row'] is None:
            recorded=route_report.get('runtime_snapshot_checks') or {}
            runtime=recorded.get('b34',{})
            assert runtime.get('raw_band_id')==route['raw_band_id'] and runtime.get('nv_row') is not None
            observation=runtime
            fixture='retained runtime NV route: '+recorded['snapshot']
        nv,selector,port=(observation[k] for k in ('nv_row','selector','rx_port'))
        assert None not in (nv,selector,port)
        for bw in range(6):
            words=[]
            for offset in offsets:
                cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);cpu.mem_map(0x80000000,0x1000000);cpu.mem_write(base,blob)
                cpu.mem_write(0x804ed5ac+4,struct.pack('<H',nv));cpu.mem_write(0x804ed5ac+6,bytes([selector]))
                cpu.mem_write(0x804ed5f8+28,struct.pack('<H',bw));cpu.mem_write(0x804f42b8+0xf0+4*nv,struct.pack('<H',port))
                cpu.mem_write(0x80900008,struct.pack('<I',0x80901000))
                cpu.reg_write(UC_ARM_REG_R0,0x80900000);cpu.reg_write(UC_ARM_REG_SP,0x80910000)
                cpu.emu_start((base+offset)|1,base+offset+42,count=100)
                assert cpu.reg_read(UC_ARM_REG_PC)==base+offset+42
                word=struct.unpack('<I',cpu.mem_read(0x80901000,4))[0]
                assert word==0x500000|(selector<<8)|(port<<4)|bw
                words.append(word)
            assert words[0]==words[1]
            cpu=Uc(UC_ARCH_RISCV,UC_MODE_RISCV32);cpu.mem_map(0,0x10000);cpu.mem_write(0,image)
            cpu.mem_map(0x30000,0x3000)
            # Simulated RFAD delivery: not a hardware execution test of the event engine.
            cpu.mem_write(0x30050,struct.pack('<H',words[0]&65535))
            pc=0x602c
            for _ in range(30):
                if pc==0x606a: break
                word=int.from_bytes(cpu.mem_read(pc,4),'little')
                exthz=next((pattern,mask) for name,pattern,mask in encodings if name=='EXTHZ')
                if word&exthz[1]==exthz[0]:
                    cpu.reg_write(X[(word>>7)&31],cpu.reg_read(X[(word>>15)&31])&65535)
                    cpu.reg_write(PC,pc+4)
                else: cpu.emu_start(pc,0x7ffffffe,count=1)
                pc=cpu.reg_read(PC)
            assert pc==0x606a
            mode=struct.unpack('<H',cpu.mem_read(0xb530,2))[0]
            assert mode==bw
            # Actual RXON finish loads context[0] then calls the retained helper.
            cpu.reg_write(X[9],0xb530)
            cpu.emu_start(0x4b26,0x7ffffffe,count=2)
            assert cpu.reg_read(PC)==0x3a7c and cpu.reg_read(X[10])==bw
            cases.append(dict(raw_band_id=route['raw_band_id'],bandwidth_index=bw,
                calibration_fixture=fixture,
                rfad_parameter_word=hex(words[0]),context_mode=mode,helper_argument=cpu.reg_read(X[10])))
    return dict(scope='native CP pack prefix in both variants, simulated RFAD delivery, native RF low-nibble decode and caller to0x3a7c',
        cp_prefix_entries=[hex(base+offset) for offset in offsets],rf_decode_entry='0x602c',
        mode_context='0xb530',finish_call='0x4b26',cases=cases)
def run(image,encodings,mode,flag,initial,correction_index=0,selector=0):
    cpu=Uc(UC_ARCH_RISCV,UC_MODE_RISCV32)
    cpu.mem_map(0,0x10000);cpu.mem_write(0,image)
    cpu.mem_map(0x30000,0x3000);cpu.mem_map(0x100000,0x10000)
    cpu.reg_write(X[2],0x108000);cpu.reg_write(X[1],0xf000);cpu.reg_write(X[10],mode)
    cpu.mem_write(0xb52a,struct.pack('<H',flag))
    cpu.mem_write(0xb550,struct.pack('<H',correction_index))
    cpu.mem_write(0xb538,struct.pack('<H',selector))
    for addr in (0x32000,0x32004): cpu.mem_write(addr,struct.pack('<H',initial))
    writes=[];extensions={}
    def observe(uc,access,address,size,value,context):
        if 0x30000<=address<0x33000:
            writes.append(dict(address=hex(address),bytes=size,value=value&((1<<(8*size))-1)))
        else: raise AssertionError('unexpected write '+hex(address))
    cpu.hook_add(UC_HOOK_MEM_WRITE,observe)
    pc=0x3a7c
    for step in range(2000):
        if pc==0xf000: break
        assert 0<=pc<len(image),hex(pc)
        word=int.from_bytes(cpu.mem_read(pc,4),'little')
        match=next((name for name,pattern,mask in encodings if word&3==3 and word&mask==pattern),None)
        if match:
            extensions[match]=extensions.get(match,0)+1
            rd=(word>>7)&31;rs1=(word>>15)&31;rs2=(word>>20)&31
            get=lambda r:cpu.reg_read(X[r]) if r else 0
            def put(r,v):
                if r:cpu.reg_write(X[r],v&0xffffffff)
            value=get(rs1);next_pc=pc+4
            if match=='EXTHZ': put(rd,value&65535)
            elif match=='BCLR':
                width=((word>>25)&31)+1;bit=(word>>20)&31
                put(rd,value&~(((1<<width)-1)<<bit))
            elif match in ('BNEM1','BEQM1'):
                disp=((word>>31)<<12)|(((word>>7)&1)<<11)|(((word>>25)&63)<<5)|(((word>>8)&15)<<1)
                equal=value==(signed(rs2,5)&0xffffffff)
                if equal==(match=='BEQM1'): next_pc=pc+signed(disp,13)
            elif match=='LHUPOST':
                put(rd,int.from_bytes(cpu.mem_read(value,2),'little'));put(rs1,value+signed(word>>20,12))
            elif match=='LWRR': put(rd,int.from_bytes(cpu.mem_read((value+get(rs2))&0xffffffff,4),'little'))
            elif match=='SHPOST':
                result=get(rs2)&65535
                assert 0x30000<=value<0x33000
                cpu.mem_write(value,struct.pack('<H',result));writes.append(dict(address=hex(value),bytes=2,value=result))
                put(rs1,value+signed(((word>>25)<<5)|rd,12))
            else: raise AssertionError(match)
            cpu.reg_write(PC,next_pc)
        else:
            try: cpu.emu_start(pc,0x7ffffffe,count=1)
            except Exception as error: raise RuntimeError('instruction at '+hex(pc)+' word '+hex(word)) from error
        pc=cpu.reg_read(PC)
    else: raise AssertionError('mode helper exceeded instruction budget')
    return dict(mode_argument=mode,digital_flag=flag,initial_register_halfword=initial,
        instruction_steps=step,legacy_extensions=extensions,writes=writes)
def main():
    reference=ROOT/'inputs/reference-source/riscv-pulp-legacy'
    header=reference/'riscv-opc.h';manifest=reference/'source-manifest.json'
    pinned=json.loads(manifest.read_text())
    assert sha(header)==next(r['sha256'] for r in pinned['files'] if r['file']=='riscv-opc.h')
    defs={k:int(v,16) for k,v in re.findall(r'#define\s+((?:MATCH|MASK)_\w+)\s+(0x[0-9a-fA-F]+)',header.read_text())}
    rules=[('EXTHZ','PALUS'),('BCLR','PALU2'),('BNEM1','BNEM1'),('BEQM1','BEQM1'),('LHUPOST','LPOST'),('SHPOST','SPOST'),('LWRR','LRR')]
    encodings=[(name,defs['MATCH_'+name],defs['MASK_'+mask]) for name,mask in rules]
    source=ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin/riscV.bin'
    image=source.read_bytes()
    cases=[run(image,encodings,mode,flag,initial) for mode in range(6) for flag in (0,1) for initial in (0,0xffff)]
    for case in cases:
        assert len(case['writes'])==45
        assert all(w['bytes']==2 and (0x32000<=int(w['address'],16)<0x32200 or int(w['address'],16)==0x325d8) for w in case['writes'])
    summaries=[]
    for mode in range(6):
        baseline=cases[mode*4]
        final={w['address']:w['value'] for w in baseline['writes']}
        summaries.append(dict(mode_argument=mode,zero_initial_registers_and_flag=True,
            control_words={a:hex(final[a]) for a in ('0x32000','0x32004','0x32054','0x32058')},
            ordered_write_count=len(baseline['writes'])))
    cp=source.with_name('cp.bin');axf=source.with_name('cp.axf')
    chain=bandwidth_chain(image,encodings,cp,axf)
    deps=[Path(__file__),source,cp,axf,header,manifest,ROOT/'tools/sdr/rf_catalog.py']+[ROOT/p for p in CATALOG_INPUTS]
    report=dict(status='passed',device_accessed=False,hardware_tested=False,
        scope='original RISC-V helper with seven locally modeled legacy PULP operations, synthetic register values and flag; no analog/filter-response proof',
        entry='0x3a7c',jump_table='0x7bc0',mode_targets=[hex(0x7bc0+x) for x in struct.unpack_from('<6i',image,0x7bc0)],
        mode_to_bw_mapping_verified=True,mode_to_bw_scope='software parameter propagation only; RFAD transport simulated',
        bandwidth_chain=chain,summaries=summaries,cases=cases,
        dependencies={p.relative_to(ROOT).as_posix():sha(p) for p in deps})
    (ROOT/'records/usb/rf-mode-native-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=report['status'],cases=len(cases),mode_targets=report['mode_targets'],
        writes_per_mode=[len(cases[4*i]['writes']) for i in range(6)],bandwidth_chain_cases=len(chain['cases'])),indent=2))
if __name__=='__main__':main()
