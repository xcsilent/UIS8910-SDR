"""Compare bounded original RF arithmetic/register prefixes with retained C.

Only EXTHZ, BCLR and BNEM1 legacy PULP instructions are modeled. Original
standard instructions, including division helpers, run in Unicorn. Synthetic
contexts test software behavior; no PLL lock, RF analog range or MMIO proof.
"""
import argparse,hashlib,json,re,struct,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/host-test-deps'))
sys.path.insert(0,str(ROOT/'tools'))
from verify_rf_mode_native import X,PC,signed
from sdr.rf_catalog import catalog
from unicorn import Uc,UC_ARCH_RISCV,UC_MODE_RISCV32,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_PC,UC_ARM_REG_SP,UC_ARM_REG_LR
from elftools.elf.elffile import ELFFile

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

class Native:
    def __init__(self,image,encodings):
        self.cpu=Uc(UC_ARCH_RISCV,UC_MODE_RISCV32)
        self.cpu.mem_map(0,0x10000);self.cpu.mem_write(0,image)
        self.cpu.mem_map(0x30000,0x3000);self.cpu.mem_map(0x100000,0x10000)
        self.cpu.reg_write(X[2],0x108000);self.cpu.reg_write(X[1],0xf000)
        self.rules=encodings;self.extensions={};self.writes=[]
        self.cpu.hook_add(UC_HOOK_MEM_WRITE,self.observe)
    def observe(self,cpu,access,address,size,value,context):
        if 0x30000<=address<0x33000:self.writes.append((address,value&((1<<(size*8))-1),size))
        else:assert 0x100000<=address<0x110000 or 0xa000<=address<0xc000,hex(address)
    def put16(self,address,value):self.cpu.mem_write(address,struct.pack('<H',value))
    def run(self,start,stops):
        pc=start
        for steps in range(5000):
            if pc in stops:return pc,steps
            word=int.from_bytes(self.cpu.mem_read(pc,4),'little')
            match=next((n for n,p,m in self.rules if word&3==3 and word&m==p),None)
            if match:
                self.extensions[match]=self.extensions.get(match,0)+1
                rd=(word>>7)&31;rs1=(word>>15)&31;rs2=(word>>20)&31
                value=self.cpu.reg_read(X[rs1]) if rs1 else 0
                next_pc=pc+4
                if match=='EXTHZ':result=value&65535
                elif match=='BCLR':result=value&~(((1<<(((word>>25)&31)+1))-1)<<rs2)
                else:
                    displacement=((word>>31)<<12)|(((word>>7)&1)<<11)|(((word>>25)&63)<<5)|(((word>>8)&15)<<1)
                    if value!=(signed(rs2,5)&0xffffffff):next_pc=pc+signed(displacement,13)
                    result=None
                if result is not None and rd:self.cpu.reg_write(X[rd],result&0xffffffff)
                self.cpu.reg_write(PC,next_pc)
            else:
                try:self.cpu.emu_start(pc,0x7ffffffe,count=1)
                except Exception as error:raise RuntimeError(f'unsupported instruction at{pc:#x}: {word:#x}') from error
            pc=self.cpu.reg_read(PC)
        raise AssertionError('native RF slice exceeded instruction budget')
    def coefficients(self,working,selector,state,factor):
        self.cpu.reg_write(X[10],working);self.cpu.reg_write(X[11],0x102000);self.cpu.reg_write(X[12],selector)
        self.put16(0xa710,state);self.put16(0x940c+2*selector,2);self.put16(0xa714+4,factor)
        self.run(0x37f0,{0xf000})
        return struct.unpack('<4H',self.cpu.mem_read(0x102000,8))
    def correction(self,requested,mode,index):
        # Enter after raw request assembly and index extraction. The native
        # entry permits bit13 indexes0/1, not arbitrary four-entry indexes.
        self.cpu.reg_write(X[15],0xb530);self.cpu.reg_write(X[14],index);self.cpu.reg_write(X[9],requested)
        self.put16(0xb530,mode);self.run(0x63c0,{0x6404})
        return int.from_bytes(self.cpu.mem_read(0xb53c,4),'little')
    def prefix(self,selector,coefficients,control):
        self.cpu.reg_write(X[18],0xb530);self.put16(0xb538,selector);self.put16(0xb464,0)
        self.cpu.mem_write(0xb520,struct.pack('<4H',*coefficients))
        self.put16(0x30364,control);self.put16(0x30374,control)
        self.writes=[];stop,steps=self.run(0x6420,{0x64c4,0x6618})
        return stop,list(self.writes)

class Replica:
    def __init__(self,path):
        self.cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM)
        self.cpu.mem_map(0x100000,0x10000);self.cpu.mem_map(0x200000,0x20000)
        with path.open('rb') as stream:
            elf=ELFFile(stream)
            for segment in elf.iter_segments():
                if segment['p_type']=='PT_LOAD':self.cpu.mem_write(segment['p_vaddr'],segment.data())
            self.symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
    def call(self,name,data,bytes_out,capacity=None):
        self.cpu.mem_write(0x210000,data);self.cpu.mem_write(0x210100,b'\xa5'*bytes_out)
        self.cpu.reg_write(UC_ARM_REG_SP,0x20f000);self.cpu.reg_write(UC_ARM_REG_LR,0x70000000)
        self.cpu.reg_write(UC_ARM_REG_R0,0x210000);self.cpu.reg_write(UC_ARM_REG_R1,0x210100)
        if capacity is not None:self.cpu.reg_write(UC_ARM_REG_R2,capacity)
        self.cpu.emu_start(self.symbols[name]|1,0x70000000,count=100000)
        assert self.cpu.reg_read(UC_ARM_REG_PC)==0x70000000
        return self.cpu.reg_read(UC_ARM_REG_R0),bytes(self.cpu.mem_read(0x210100,bytes_out))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current-pac',action='store_true',help='verify decoded current PAC coefficient helper, including its known frequency witness; SDK retune slices are not executed')
    parser.add_argument('--working-raw',type=int,nargs='+',help='specific working frequencies in100Hz units; no configuration or hardware writes')
    parser.add_argument('--output',type=Path,help='independent project evidence path for a focused arithmetic question')
    args=parser.parse_args()
    if args.working_raw and any(not 0<v<0x80000000 for v in args.working_raw):parser.error('working-raw must be positive uint31 values')
    if args.output and (not args.output.resolve().is_relative_to(ROOT) or args.output.exists()):parser.error('choose a new project report')
    build=ROOT/'work/rf-frequency-native';build.mkdir(exist_ok=True)
    source=ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin/riscV.bin'
    provenance=[]
    if args.current_pac:
        from rf_image import current_pac_image
        source,provenance=current_pac_image()
    class CurrentFrequency(Native):
        def observe(self,cpu,access,address,size,value,context):
            if address==0x66ac:
                assert size==4
                self.witness=value
            else:super().observe(cpu,access,address,size,value,context)
    machine=CurrentFrequency if args.current_pac else Native
    reference=ROOT/'inputs/reference-source/riscv-pulp-legacy'
    header=reference/'riscv-opc.h';manifest=reference/'source-manifest.json'
    assert sha(header)==next(p['sha256'] for p in json.loads(manifest.read_text())['files'] if p['file']=='riscv-opc.h')
    definitions={k:int(v,16) for k,v in re.findall(r'#define\s+((?:MATCH|MASK)_\w+)\s+(0x[0-9a-fA-F]+)',header.read_text())}
    rules=[(n,definitions['MATCH_'+n],definitions['MASK_'+m]) for n,m in [('EXTHZ','PALUS'),('BCLR','PALU2'),('BNEM1','BNEM1')]]
    cdir=ROOT/'firmware/rf_rebuild';gcc=ROOT/'inputs/repositories/rda8910-csdk-hotelec/prebuilts/win32/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
    elf=build/'replica.elf'
    subprocess.run([str(gcc),'-mcpu=cortex-a5','-mthumb','-mfloat-abi=soft','-Os','-ffreestanding','-fno-builtin','-nostdlib',
        '-Wl,--build-id=none','-Wl,-Ttext=0x100000','-Wl,-e,rf_core_frequency_coefficients',
        *[str(cdir/name) for name in ('rf_core_frequency.c','rf_core_tune_flow.c','rf_core_tune_plan.c')],'-lgcc','-o',str(elf)],check=True)
    replica=Replica(elf);image=source.read_bytes();rows=[]
    frequencies=[8240000,8690000,8800000,9425000,9700000,9800000,9992999,9993000,9999999,10000000,10000001,17100000,18425000,20000000,23300000,26000000,27812500]
    if args.working_raw:frequencies=args.working_raw
    for working in frequencies:
        for state,factor in ((0,8),(1,7),(1,8)):
            native=machine(image,rules);expected=native.coefficients(working,6,state,factor)
            if args.current_pac:assert native.witness==working
            error,actual=replica.call('rf_core_frequency_coefficients',struct.pack('<IHH',working,state,factor),8)
            assert not error and struct.unpack('<4H',actual)==expected,(working,state,factor)
            rows.append(dict(working_raw=working,factor_state=state,table_factor=factor,q8=expected[0],
                fraction=(expected[1]<<16)|expected[2],selected_factor=expected[3],
                effective_raw=working*2 if working<10000000 else working))
    corrections=[]
    for mode in (() if args.current_pac else (0,6)):
        for index in (0,1):
            for requested in (9992999,9993000,10000000):
                native=Native(image,rules);working=native.correction(requested,mode,index)
                values=native.coefficients(working,6,0,7)
                error,data=replica.call('rf_core_calculate_tune_parameters',struct.pack('<I4H',requested,mode,index,0,7),24)
                fields=struct.unpack('<IIIh5H',data)
                assert not error and fields[0]==working and fields[2]==(values[1]<<16)|values[2] and fields[4:6]==(values[3],values[0])
                corrections.append(dict(mode=mode,index=index,requested_raw=requested,working_raw=working,correction=fields[3],effective_raw=fields[1]))
    banks=[]
    for selector in (() if args.current_pac else range(21)):
        for control in (0,65535):
            values=(0x4567,0x1234,0xabcd,7);native=Native(image,rules);stop,writes=native.prefix(selector,values,control)
            error,data=replica.call('rf_core_make_retune_plan',struct.pack('<9H',selector,1,control,values[0],values[2],values[1],0,0,0),11*8,11)
            expected=[(a,v,2) for a,v,_ in struct.iter_unpack('<IHH',data[:7*8])]
            assert error==9 and writes==expected,(selector,control,writes,expected)
            if control==0:banks.append(dict(selector=selector,register_group='B' if stop==0x6618 else 'A',coefficient_addresses=[hex(w[0]) for w in writes[4:7]]))
    report=dict(status='passed',device_accessed=False,hardware_tested=False,
        image_source='current PAC decoded payload' if args.current_pac else 'SDK reference RF binary',
        image_sha256=sha(source),frequency_witness_verified=args.current_pac,
        scope=('Current PAC coefficient helper with working-raw witness vs compiled current C; SDK retune/correction addresses not reused. Synthetic contexts, no analog/lock proof' if args.current_pac else 'Original native RF correction slice, coefficient helper incl standard division code, and first7 retune writes vs compiled current C; synthetic contexts, no analog/lock proof'),
        native_entries=dict(coefficients='0x37f0',**({} if args.current_pac else dict(correction='0x63c0..0x6404',prefix='0x6420..0x64c4 or0x6618'))),
        modeled_legacy_operations=['EXTHZ','BCLR','BNEM1'],coefficient_cases=rows,correction_cases=corrections,register_groups=banks,
        conclusion=('Current PAC coefficient outputs agree with C for tested contexts and frequency witness stores input after coefficient calculation; not an execution counter or RF lock proof.' if args.current_pac else 'Working raw<10000000 doubles arithmetic input. Request threshold depends on signed correction;999.3MHz applies to mode0/index0 only. Register groups follow selector, not frequency alone. Physical LO divider and lock remain unproven.'),
        dependencies={p.relative_to(ROOT).as_posix():sha(p) for p in [Path(__file__),ROOT/'tools/verify/verify_rf_mode_native.py',source,header,manifest,elf]+list(cdir.glob('rf_core_frequency.[ch]'))+list(cdir.glob('rf_core_tune_flow.[ch]'))+list(cdir.glob('rf_core_tune_plan.[ch]'))+provenance})
    output=args.output or ROOT/('records/rf/reference-rf-current-pac-frequency.json' if args.current_pac else 'records/rf/runtime-frequency-native-verification.json');output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status='passed',coefficient_cases=len(rows),correction_cases=len(corrections),register_prefix_cases=len(banks)*2,output=output.resolve().relative_to(ROOT).as_posix()),indent=2))

if __name__=='__main__':main()
