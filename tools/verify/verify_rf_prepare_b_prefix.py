"""Original B prepare prefix vs compiled C, offline, no deployment or MMIO.

Compare B RXON body composition, reads/writes/callbacks and fail-stop at every
access; execute original coefficient producer/dispatch. Shared cal/mode
internals remain explicit callback boundaries, not hardware emulation.
"""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path
from datetime import datetime

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/verify'))
from verify_rf_frequency_native import Native, Replica
from verify_rf_mode_native import X, PC, signed
from unicorn import UC_HOOK_MEM_READ
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'records/rf/reference-b-prepare-prefix.json')
    parser.add_argument('--runtime-snapshot',type=Path,help='retained stopped NV/table snapshot; never queries devices')
    parser.add_argument('--frontend-snapshot',type=Path,help='paired full NV snapshot, same epoch as runtime snapshot')
    parser.add_argument('--board-request-raw',type=int,nargs='+',help='focused retained-route request frequencies in100Hz units; synthetic execution only')
    args=parser.parse_args()
    if bool(args.runtime_snapshot)!=bool(args.frontend_snapshot):parser.error('supply both paired snapshot reports')
    sdk=ROOT/'inputs/repositories/rda8910-csdk-hotelec'
    image_path=sdk/'core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin/riscV.bin'
    image=image_path.read_bytes()
    header=ROOT/'inputs/reference-source/riscv-pulp-legacy/riscv-opc.h'
    manifest=header.with_name('source-manifest.json')
    assert sha(header)==next(x['sha256'] for x in json.loads(manifest.read_text())['files'] if x['file']==header.name)
    for name in ('riscv-opc.c','ri5cy_user_manual.pdf'):
        assert sha(header.with_name(name))==next(x['sha256'] for x in json.loads(manifest.read_text())['files'] if x['file']==name)
    definitions={k:int(v,16) for k,v in re.findall(r'#define\s+((?:MATCH|MASK)_\w+)\s+(0x[\da-fA-F]+)',header.read_text())}
    rules=[('EXTHZ',definitions['MATCH_EXTHZ'],definitions['MASK_PALUS'])]
    class Prefix(Native):
        def observe(self,cpu,access,address,size,value,context):
            assert 0x30000<=address<0x33000 and size==2
            self.accesses.append((1,address,value&65535))
    def original(field,factor,initial):
        n=Prefix(image,rules);n.accesses=[]
        n.cpu.reg_write(X[8],0x30000);n.cpu.reg_write(X[9],0xb530)
        n.cpu.reg_write(X[13],0xb520);n.cpu.reg_write(X[20],0x5000)
        for address,value in [(0xb534,field),(0xb526,factor),(0x30410,initial),
                              (0x302c0,initial),(0x3049c,initial)]:n.put16(address,value)
        for address in (0x8a54+10*field+x for x in (0,2,4,8)):
            n.put16(address,((address*73)^0x5a3c)&65535)
        address=0x8184+2*field;n.put16(address,((address*73)^0x5a3c)&65535)
        def read(cpu,access,address,size,value,context):
            assert size==2
            n.accesses.append((0,address,int.from_bytes(cpu.mem_read(address,size),'little')))
        n.cpu.hook_add(UC_HOOK_MEM_READ,read)
        n.run(0x4fc4,{0x50da})
        assert len(n.accesses)==26 and sum(op for op,a,v in n.accesses)==11, n.accesses
        return n.accesses
    cases=[]
    for field in (0,1,3,7,15):
        for factor in (7,8,9,10):
            for initial in (0,0x7fff,0x8000,0xa55a,0xffff):
                cases.append((field,factor,initial,original(field,factor,initial)))
    def original_enter(field,flag,initial):
        n=Prefix(image,rules);n.accesses=[]
        n.cpu.reg_write(X[10],0xb530)
        for a,v in [(0xb534,field),(0xb52a,flag),(0x30400,initial),
                    (0x30404,initial^65535),(0x30480,initial)]:n.put16(a,v)
        a=0x8a54+10*field+6;n.put16(a,((a*73)^0x5a3c)&65535)
        n.cpu.hook_add(UC_HOOK_MEM_READ,lambda cpu,access,a,size,v,ctx:
            n.accesses.append((0,a,int.from_bytes(cpu.mem_read(a,size),'little'))))
        n.run(0x4ecc,{0x4f90})
        assert n.cpu.reg_read(X[18])==initial and n.cpu.reg_read(X[19])==initial^65535
        return n.accesses
    enter_cases=[((field,flag,initial),original_enter(field,flag,initial))
                 for field in (0,1,3,7) for flag in (0,1,2,65535) for initial in (0,0xa55a,65535)]
    n=Prefix(image,rules);n.accesses=[]
    n.cpu.reg_write(X[8],0x30000)
    for a in (0xb520,0xb522,0xb524):n.put16(a,((a*73)^0x5a3c)&65535)
    n.cpu.hook_add(UC_HOOK_MEM_READ,lambda cpu,access,a,size,v,ctx:
        n.accesses.append((0,a,int.from_bytes(cpu.mem_read(a,size),'little'))))
    n.run(0x4f98,{0x4fc4});commit_expected=n.accesses
    reset_cases=[]
    class Reset(Native):
        def observe(self,cpu,access,a,size,v,context):
            assert size==2 and a in (0xb46e,0xb4d0,0xb4de,0xb4e0)
    for initial in (0,1,0xa55a,65535):
        n=Reset(image,[]);n.put16(0xb4e0,initial);n.run(0x10c2,{0x10da})
        assert int.from_bytes(n.cpu.mem_read(0xb4e0,2),'little')==0
        reset_cases.append(dict(initial=initial,result=0))
    clock_rules=[(name,definitions['MATCH_'+name],definitions['MASK_'+mask])
        for name,mask in [('LWRR','LRR'),('BNEM1','BNEM1'),('BEQM1','BEQM1')]]
    def original_clock(mode,selector):
        n=Prefix(image,[]);n.accesses=[]
        n.cpu.reg_write(X[10],mode);n.cpu.reg_write(X[1],0xf000);n.put16(0xb538,selector)
        def clock_read(cpu,access,a,size,v,ctx):
            if a==0xb538:n.accesses.append((0,a,int.from_bytes(cpu.mem_read(a,size),'little')))
        n.cpu.hook_add(UC_HOOK_MEM_READ,clock_read)
        pc=0x4632
        for step in range(100):
            if pc==0xf000:return n.accesses
            word=int.from_bytes(n.cpu.mem_read(pc,4),'little')
            match=next((name for name,pattern,mask in clock_rules if word&3==3 and word&mask==pattern),None)
            if match:
                rd=(word>>7)&31;rs1=(word>>15)&31;rs2=(word>>20)&31
                value=n.cpu.reg_read(X[rs1]) if rs1 else 0;next_pc=pc+4
                if match=='LWRR':
                    address=(value+(n.cpu.reg_read(X[rs2]) if rs2 else 0))&0xffffffff
                    if rd:n.cpu.reg_write(X[rd],int.from_bytes(n.cpu.mem_read(address,4),'little'))
                else:
                    disp=((word>>31)<<12)|(((word>>7)&1)<<11)|(((word>>25)&63)<<5)|(((word>>8)&15)<<1)
                    if (value==(signed(rs2,5)&0xffffffff))==(match=='BEQM1'):next_pc=pc+signed(disp,13)
                n.cpu.reg_write(PC,next_pc)
            else:n.cpu.emu_start(pc,0x7ffffffe,count=1)
            pc=n.cpu.reg_read(PC)
        raise AssertionError('clock-mode helper budget exceeded')
    clock_cases=[((mode,selector,0),original_clock(mode,selector))
                 for mode in (0,1,2,3,4,5,6,7,65535) for selector in (4,5,14,15,16)]
    # B completion before shared calibration and mode calls. This is not a
    # proof about the internals of either cal-ready production or the callee.
    tail_cases=[]
    tail_rules=[(name,definitions['MATCH_'+name],definitions['MASK_'+mask])
                for name,mask in [('EXTHZ','PALUS'),('BCLR','PALU2'),('BSET','PALU2')]]
    for field in (0,3,7):
        for digital_flag in (0,1,2,65535):
            n=Prefix(image,[]);n.accesses=[]
            n.cpu.reg_write(X[9],0xb530)
            for address,value in [(0xb534,field),(0xb52a,digital_flag),
                                  (0x304b4,0xa55a),(0x8a54+10*field+8,0x1928)]:n.put16(address,value)
            n.cpu.hook_add(UC_HOOK_MEM_READ,lambda cpu,access,a,size,v,ctx,n=n:
                n.accesses.append((0,a,int.from_bytes(cpu.mem_read(a,size),'little'))))
            pc=0x529c
            for step in range(150):
                if pc==0x5354:break
                word=int.from_bytes(n.cpu.mem_read(pc,4),'little')
                match=next((name for name,pattern,mask in tail_rules if word&3==3 and word&mask==pattern),None)
                if match:
                    rd=(word>>7)&31;rs1=(word>>15)&31
                    value=n.cpu.reg_read(X[rs1]) if rs1 else 0
                    mask=((1<<(((word>>25)&31)+1))-1)<<((word>>20)&31)
                    result=value&65535 if match=='EXTHZ' else value&~mask if match=='BCLR' else value|mask
                    if rd:n.cpu.reg_write(X[rd],result&0xffffffff)
                    n.cpu.reg_write(PC,pc+4)
                else:n.cpu.emu_start(pc,0x7ffffffe,count=1)
                pc=n.cpu.reg_read(PC)
            else:raise AssertionError('B tail budget exceeded')
            assert n.cpu.reg_read(X[10])==0xb530
            writes=[(a,v) for op,a,v in n.accesses if op]
            expected=[(0x30364,0xb3),(0x30408,0x4844)]
            if not digital_flag:expected.append((0x30498,7))
            expected.extend([(0x30414,0x1928|0x40),(0x304b4,0xa55a&~0x200),
                             (0x302cc,0x60),(0x30414,0x1928|0x60),(0x304b4,0xa55a|0x200)])
            assert writes==expected,(writes,expected)
            assert all(a not in (0x3036c,0x3037c) for op,a,v in n.accesses)
            tail_cases.append(dict(field=field,digital_flag=digital_flag,writes=[(hex(a),hex(v)) for a,v in writes]))
    def jal_target(pc):
        word=int.from_bytes(image[pc:pc+4],'little')
        assert word&0x7f==0x6f
        imm=((word>>31)<<20)|(((word>>12)&255)<<12)|(((word>>20)&1)<<11)|(((word>>21)&1023)<<1)
        if imm&(1<<20):imm-=1<<21
        return pc+imm
    assert jal_target(0x5354)==0x453c and jal_target(0x535c)==0x3a7c
    forwarded_modes=[]
    for mode in range(6):
        n=Native(image,[]);n.cpu.reg_write(X[9],0xb530);n.put16(0xb530,mode)
        n.run(0x5358,{0x3a7c})
        assert n.cpu.reg_read(X[10])==mode
        forwarded_modes.append(mode)
    middle_rules=[(name,definitions['MATCH_'+name],definitions['MASK_'+mask])
        for name,mask in [('EXTHZ','PALUS'),('BSET','PALU2'),('BNEM1','BNEM1'),('BEQM1','BEQM1')]]
    visited_middle=set()
    def original_middle(mode,selector,analog_flag,digital_flag,saved400,saved404):
        n=Prefix(image,[]);n.accesses=[]
        n.cpu.reg_write(X[9],0xb530);n.cpu.reg_write(X[18],saved400);n.cpu.reg_write(X[19],saved404)
        for address,value in [(0xb530,mode),(0xb538,selector),(0xb4e0,analog_flag),(0xb52a,digital_flag)]:
            n.put16(address,value)
        n.cpu.hook_add(UC_HOOK_MEM_READ,lambda cpu,access,a,size,v,ctx:
            n.accesses.append((0,a,int.from_bytes(cpu.mem_read(a,size),'little'))))
        pc=0x50da
        for step in range(200):
            if pc==0x529c:return n.accesses
            visited_middle.add(pc)
            word=int.from_bytes(n.cpu.mem_read(pc,4),'little')
            match=next((name for name,pattern,mask in middle_rules if word&3==3 and word&mask==pattern),None)
            if match:
                rd=(word>>7)&31;rs1=(word>>15)&31;rs2=(word>>20)&31
                value=n.cpu.reg_read(X[rs1]) if rs1 else 0
                next_pc=pc+4
                if match in ('BNEM1','BEQM1'):
                    disp=((word>>31)<<12)|(((word>>7)&1)<<11)|(((word>>25)&63)<<5)|(((word>>8)&15)<<1)
                    equal=value==(signed(rs2,5)&0xffffffff)
                    if equal==(match=='BEQM1'):next_pc=pc+signed(disp,13)
                else:
                    result=value&65535 if match=='EXTHZ' else value|(((1<<(((word>>25)&31)+1))-1)<<rs2)
                    if rd:n.cpu.reg_write(X[rd],result&0xffffffff)
                n.cpu.reg_write(PC,next_pc)
            else:n.cpu.emu_start(pc,0x7ffffffe,count=1)
            pc=n.cpu.reg_read(PC)
        raise AssertionError('B middle instruction budget exceeded')
    middle_cases=[]
    for mode in (0,1,2,3,4,5,6,7,65535):
        for selector in (4,5,14,15,16):
            for analog_flag,digital_flag in ((0,0),(0,2),(1,0),(2,1),(65535,65535)):
                for saved in (0,0xa55a,65535):
                    values=(mode,selector,analog_flag,digital_flag,saved,saved^0xffff)
                    middle_cases.append((values,original_middle(*values)))
    # Every instruction boundary in the middle is exercised, not an acceptance
    # gate for any other registers or native modes. No skipped legacy opcodes.
    boundaries=set();pc=0x50da
    while pc<0x529c:
        boundaries.add(pc);pc+=4 if image[pc]&3==3 else 2
    assert visited_middle==boundaries,(boundaries-visited_middle)
    full_rules=[(name,definitions['MATCH_'+name],definitions['MASK_'+mask]) for name,mask in
        [('EXTHZ','PALUS'),('EXTHS','PALUS'),('EXTRACTU','PALU2'),('BCLR','PALU2'),('BSET','PALU2'),('LWRR','LRR'),('BNEM1','BNEM1'),('BEQM1','BEQM1'),
         ('LHUPOST','LPOST'),('SHPOST','SPOST')]]
    def original_full(values,execute_shared=False,status_word=0,portable_bus=False,slot=0,context16=0,request=None,retained_analog=False):
        mode,selector,field,analog,digital,factor,initial,mode_after_cal=values
        class BodyNative(Prefix):
            def observe(self,cpu,access,address,size,value,context):
                if 0x100000<=address<0x110000:return
                if request is not None:
                    n.accesses.append((1 if size==2 else 3,address,value&((1<<(8*size))-1)))
                    n.stages.append(n.stage);return
                super().observe(cpu,access,address,size,value,context)
                if portable_bus:n.stages.append(n.stage)
        n=BodyNative(image,[]);n.accesses=[];n.cpu.reg_write(X[10],0xb530)
        n.stages=[];n.stage=-2
        for a,v in [(0xb530,mode),(0xb534,field),(0xb538,selector),(0xb4e0,analog),
                    (0xb52a,digital),(0xb526,factor),(0x30404,initial^65535)]:n.put16(a,v)
        for a in (0x30400,0x30480,0x30410,0x302c0,0x3049c):n.put16(a,initial)
        n.put16(0x3036c,status_word);n.put16(0x3037c,status_word)
        n.put16(0xb544,slot);n.put16(0xb546,context16)
        for a in [0x8184+2*field,0xb520,0xb522,0xb524]+[0x8a54+10*field+x for x in (0,2,4,6,8)]:
            n.put16(a,((a*73)^0x5a3c)&65535)
        if retained_analog:
            # Use the retained image's actual analog row, rather than the
            # synthetic values used to detect hardcoded C implementations.
            # This is binary-default evidence, never a live RF RAM claim.
            for a in [0x8184+2*field]+[0x8a54+10*field+x for x in (0,2,4,6,8)]:
                n.put16(a,struct.unpack_from('<H',image,a)[0])
        if request is not None:
            word,aux,raw,zfif,state,selected_factor=request
            for a,v in ((0x30050,word),(0x30054,aux),(0x30058,raw&65535),(0x30008,raw>>16),
                        (0xb4de,zfif),(0xa710,state),(0x940c+2*selector,2),(0xa718,selected_factor)):
                n.put16(a,v)
        def full_read(cpu,access,a,size,v,ctx):
            if portable_bus:
                if 0x100000<=a<0x110000:return
                # Original division support reads a private immutable byte
                # lookup table. ARM libgcc implements the same arithmetic
                # without a public bus lookup; retain correction7b70 reads.
                if request is not None and a<0x7b70:
                    assert bytes(cpu.mem_read(a,size))==image[a:a+size]
                    return
                # The portable mode module embeds the verified immutable
                # image tables; these private loads are not bus callbacks.
                if n.stage==-4 and a<0x30000 and not 0xb500<=a<0xb600:
                    if request is not None:
                        assert bytes(cpu.mem_read(a,size))==image[a:a+size],('mode constant changed by request fixture',hex(a),size)
                    return
                n.stages.append(n.stage)
            n.accesses.append((2 if request is not None and size==4 else 0,a,int.from_bytes(cpu.mem_read(a,size),'little')))
        n.cpu.hook_add(UC_HOOK_MEM_READ,full_read)
        pc=0x602c if request is not None else 0x4ecc
        for step in range(10000 if request is not None else 2500 if execute_shared else 700):
            if pc==0x5360:return (n.accesses,n.stages) if portable_bus else n.accesses
            n.stage=-3 if 0x453c<=pc<0x4632 else -4 if 0x3a7c<=pc<0x453c else -2
            if not execute_shared and pc in (0x453c,0x3a7c):
                if pc==0x453c:
                    assert n.cpu.reg_read(X[10])==0xb530
                    n.accesses.append((2,0xb530,0))
                    if mode_after_cal<=65535:n.put16(0xb530,mode_after_cal)
                else:n.accesses.append((3,0x3a7c,n.cpu.reg_read(X[10])))
                pc=n.cpu.reg_read(X[1]);n.cpu.reg_write(PC,pc);continue
            word=int.from_bytes(n.cpu.mem_read(pc,4),'little')
            match=next((name for name,pattern,mask in full_rules if word&3==3 and word&mask==pattern),None)
            if match:
                rd=(word>>7)&31;rs1=(word>>15)&31;rs2=(word>>20)&31
                value=n.cpu.reg_read(X[rs1]) if rs1 else 0;next_pc=pc+4
                if match in ('BNEM1','BEQM1'):
                    disp=((word>>31)<<12)|(((word>>7)&1)<<11)|(((word>>25)&63)<<5)|(((word>>8)&15)<<1)
                    if (value==(signed(rs2,5)&0xffffffff))==(match=='BEQM1'):next_pc=pc+signed(disp,13)
                else:
                    if match=='EXTHZ':result=value&65535
                    elif match=='EXTHS':result=signed(value&65535,16)
                    elif match=='EXTRACTU':result=(value>>rs2)&((1<<(((word>>25)&31)+1))-1)
                    elif match=='LWRR':
                        address=(value+(n.cpu.reg_read(X[rs2]) if rs2 else 0))&0xffffffff
                        result=int.from_bytes(n.cpu.mem_read(address,4),'little')
                    elif match=='LHUPOST':
                        result=int.from_bytes(n.cpu.mem_read(value,2),'little')
                        if not portable_bus or n.stage!=-4 or value>=0x30000 or 0xb500<=value<0xb600:
                            n.accesses.append((0,value,result))
                            if portable_bus:n.stages.append(n.stage)
                        if rs1:n.cpu.reg_write(X[rs1],(value+signed(word>>20,12))&0xffffffff)
                    elif match=='SHPOST':
                        result=None
                        stored=n.cpu.reg_read(X[rs2])&65535 if rs2 else 0
                        assert 0x30000<=value<0x33000
                        n.cpu.mem_write(value,struct.pack('<H',stored));n.accesses.append((1,value,stored))
                        if portable_bus:n.stages.append(n.stage)
                        if rs1:n.cpu.reg_write(X[rs1],(value+signed(((word>>25)<<5)|rd,12))&0xffffffff)
                    else:
                        mask=((1<<(((word>>25)&31)+1))-1)<<rs2
                        result=value&~mask if match=='BCLR' else value|mask
                    if rd and result is not None:n.cpu.reg_write(X[rd],result&0xffffffff)
                n.cpu.reg_write(PC,next_pc)
            else:n.cpu.emu_start(pc,0x7ffffffe,count=1)
            pc=n.cpu.reg_read(PC)
        raise AssertionError('B composed body exceeded budget')
    full_cases=[]
    for mode in range(7):
        for selector in (4,5,15):
            for field in (0,3,7):
                for analog,digital in ((0,0),(1,0),(0,2),(65535,65535)):
                    values=(mode,selector,field,analog,digital,7,0xa55a,0xffffffff)
                    full_cases.append((values,original_full(values)))
    for initial in (0,65535):
        for mode in range(6):
            values=(mode,4,3,0,1,9,initial,(mode+1)%6)
            full_cases.append((values,original_full(values)))
    # Execute shared helpers too, specifically to test whether B RXON consumes
    # calibration feedback. Ready-clear and all-ones states must yield the same
    # ordered hardware operations; this does not model autonomous calibration.
    feedback_cases=[]
    for mode in range(6):
        for selector,port in ((2,1),(4,2),(6,3)):
            values=(mode,selector,port,0,0,7,0xa55a,0xffffffff)
            clear=original_full(values,True,0)
            ready=original_full(values,True,65535)
            assert clear==ready
            assert not any(op==0 and address in (0x3036c,0x3037c) for op,address,value in clear)
            assert [(a,v) for op,a,v in clear if op==1 and a==0x30364]==[(0x30364,0x33),(0x30364,0xb3)]
            assert len([1 for op,a,v in clear if op==1 and 0x32000<=a<0x32200])>=45
            feedback_cases.append(dict(mode=mode,selector=selector,rx_port=port,
                register_reads=sum(op==0 and 0x30000<=a<0x33000 for op,a,v in clear),
                writes=sum(op==1 for op,a,v in clear),ready_clear_and_set_identical=True,
                calibration_feedback_read=False))
    integrated_cases=[]
    for mode in range(6):
        for selector,port in ((2,1),(4,2),(5,2),(6,3),(17,1)):
            for analog,digital,slot,control in ((0,0,0,0),(1,1,7,0x50),(65535,2,14,0xffff)):
                values=(mode,selector,port,analog,digital,7+(mode%3),0xa55a if digital else 0,0xffffffff)
                trace,stages=original_full(values,True,0,True,slot,control)
                assert len(trace)==len(stages) and set(stages)=={-2,-3,-4}
                touched=set();initial={}
                for op,a,v in trace:
                    if not op and a not in touched:initial[a]=v
                    touched.add(a)
                integrated_cases.append((values,slot,control,trace,stages,sorted(initial.items())))
    def initial_cells(trace):
        touched=set();initial={}
        for op,a,v in trace:
            for offset in range(0,4 if op>=2 else 2,2):
                if op%2==0 and a+offset not in touched:initial[a+offset]=(v>>(8*offset))&65535
                touched.add(a+offset)
        return sorted(initial.items())
    request_cases=[]
    for mode in range(6):
        for selector,port in ((2,1),(4,2),(5,2),(6,3),(17,1)):
            for variant,raw in enumerate((6812500,6875000,9992999,9993000,10000000)):
                slot=(variant*3)%15;control=0x123
                word=mode|(port<<4)|(selector<<8)|((variant%4)<<13)
                request=(word,(slot<<12)|control,raw,variant%4,variant%2,7+variant%3)
                values=(mode,selector,port,variant%2,variant%3,7,0xa55a,0xffffffff)
                trace,stages=original_full(values,True,0,True,slot,control,request)
                request_cases.append((request,trace,stages,initial_cells(trace)))
    # Standalone shared0x453c with nonzero slot/control contexts, compared
    # against the extracted A-group C implementation below.
    tables_cases=[]
    for mode in range(7):
        for selector in (2,4,6,15):
            for slot in (0,7,14):
                for control in (0,0x1234,65535):
                    n=Prefix(image,[("BNEM1",definitions['MATCH_BNEM1'],definitions['MASK_BNEM1'])]);n.accesses=[]
                    n.cpu.reg_write(X[10],0xb530)
                    for a,v in ((0xb530,mode),(0xb538,selector),(0xb544,slot),(0xb546,control)):
                        n.put16(a,v)
                    index=15*selector+slot
                    for a in (0x8764+2*index,0x9438+2*index,0xaf78+4*index,0xaf7a+4*index):
                        n.put16(a,((a*73)^0x5a3c)&65535)
                    n.cpu.hook_add(UC_HOOK_MEM_READ,lambda cpu,access,a,size,v,ctx:
                        n.accesses.append((0,a,int.from_bytes(cpu.mem_read(a,size),'little'))))
                    n.run(0x453c,{0xf000})
                    assert not any(op==0 and 0x30000<=a<0x40000 for op,a,v in n.accesses)
                    assert len([1 for op,a,v in n.accesses if op==1])==9
                    tables_cases.append(((mode,selector,slot,control),n.accesses))
    dispatch_rules=[(name,definitions['MATCH_'+name],definitions['MASK_'+mask]) for name,mask in
        [('EXTHZ','PALUS'),('BCLR','PALU2'),('BNEM1','BNEM1')]]
    dispatch_cases=[]
    for selector in range(21):
        for working in (7007000,8815000,23307000):
            for state in (0,1):
                n=Native(image,dispatch_rules)
                n.cpu.reg_write(X[12],selector)
                n.cpu.mem_write(0xb53c,struct.pack('<I',working));n.put16(0xb538,selector)
                n.put16(0xa710,state);n.put16(0x940c+2*selector,2);n.put16(0xa718,9)
                # Poison output to establish actual native writes before dispatch.
                n.cpu.mem_write(0xb520,b'\xa5'*8)
                stop,_=n.run(0x6122,{0x4ec8,0x46f6})
                assert stop==(0x4ec8 if selector<=12 or selector==17 else 0x46f6)
                assert n.cpu.reg_read(X[10])==0xb530
                q8,high,low,factor=struct.unpack('<4H',n.cpu.mem_read(0xb520,8))
                effective=working*2 if working<10000000 else working
                expected_factor=9 if state==1 else 7
                fraction=(effective*(1<<28)//(260000*expected_factor))&0xffffffff
                assert (q8,high,low,factor)==((effective*256//260000)&65535,fraction>>16,fraction&65535,expected_factor)
                dispatch_cases.append(dict(selector=selector,working_raw=working,table_enable=state,
                    factor=factor,coefficient_words=[q8,high,low,factor],rxon_target=hex(stop)))
    # Shared post-RX helper, called after either RXON group. Execute its
    # actual instructions and compare runtime table reads as well as writes.
    post_rules=[(name,definitions['MATCH_'+name],definitions['MASK_'+mask])
        for name,mask in [('EXTHZ','PALUS'),('BCLR','PALU2'),('BSET','PALU2'),
                          ('BEQM1','BEQM1'),('BNEM1','BNEM1'),('LWRR','LRR')]]
    def original_post(values):
        frequency,mode,selector,control,*rest=values
        centers=rest[:4];width=rest[4]
        class Post(Native):
            def observe(self,cpu,access,a,size,v,ctx):
                assert (size==2 and 0x30000<=a<0x33000) or (a==0x50109050 and size==4)
                self.accesses.append((1+(2 if size==4 else 0),a,v&((1<<(8*size))-1)))
        n=Post(image,[]);n.accesses=[]
        n.cpu.mem_map(0x50109000,0x1000)
        n.cpu.reg_write(X[10],frequency);n.cpu.reg_write(X[11],mode)
        n.put16(0xb538,selector);n.put16(0x32004,control)
        n.cpu.mem_write(0x8530,struct.pack('<4I',*centers))
        n.cpu.mem_write(0x91a0+4*mode,struct.pack('<I',width))
        n.cpu.hook_add(UC_HOOK_MEM_READ,lambda cpu,access,a,size,v,ctx:
            n.accesses.append((2 if size==4 else 0,a,int.from_bytes(cpu.mem_read(a,size),'little'))))
        pc=0x38a8
        for _ in range(180):
            if pc==0xf000:return n.accesses
            word=int.from_bytes(n.cpu.mem_read(pc,4),'little')
            match=next((name for name,pattern,mask in post_rules if word&3==3 and word&mask==pattern),None)
            if match:
                rd=(word>>7)&31;rs1=(word>>15)&31;rs2=(word>>20)&31
                value=n.cpu.reg_read(X[rs1]) if rs1 else 0;next_pc=pc+4;result=None
                if match=='EXTHZ':result=value&65535
                elif match in ('BSET','BCLR'):
                    mask=((1<<(((word>>25)&31)+1))-1)<<rs2
                    result=value|mask if match=='BSET' else value&~mask
                elif match=='LWRR':
                    a=(value+(n.cpu.reg_read(X[rs2]) if rs2 else 0))&0xffffffff
                    result=int.from_bytes(n.cpu.mem_read(a,4),'little')
                    # Unicorn API reads do not trigger the guest load hook.
                    n.accesses.append((2,a,result))
                else:
                    disp=((word>>31)<<12)|(((word>>7)&1)<<11)|(((word>>25)&63)<<5)|(((word>>8)&15)<<1)
                    if (value==(signed(rs2,5)&0xffffffff))==(match=='BEQM1'):next_pc=pc+signed(disp,13)
                if result is not None and rd:n.cpu.reg_write(X[rd],result&0xffffffff)
                n.cpu.reg_write(PC,next_pc)
            else:n.cpu.emu_start(pc,0x7ffffffe,count=1)
            pc=n.cpu.reg_read(PC)
        raise AssertionError('post-RX helper budget exceeded')
    default_centers=struct.unpack_from('<4I',image,0x8530)
    default_widths=struct.unpack_from('<7I',image,0x91a0)
    post_values=set()
    for mode,width in enumerate(default_widths):
        frequencies={6812500,6875000,0,0xffffffff,19620000,19620001,19700000,19700001}
        for start,span in [(7820000,300000)]+[(s,400000) for s in (17620000,19600000,21580000,23560000,25540000)]:
            frequencies.update([start-1,start,start+span,start+span+1])
        for center in default_centers:
            frequencies.update([center-width-1,center-width,center,center+width,center+width+1])
        for selector in (1,4,5,15):
            for frequency in frequencies:
                post_values.add((frequency,mode,selector,0xa55a,*default_centers,width))
    # Non-default runtime tables expose implementations hardcoding image data.
    for selector in (1,4,5):
        for mode in (0,4,6):
            for frequency in (6800000,6812500,6875000,7000000):
                post_values.add((frequency,mode,selector,0xffff,6800000,6812500,6875000,7000000,500))
    post_cases=[(values,original_post(values)) for values in sorted(post_values)]
    gap_post_cases=[]
    if args.board_request_raw:
        for mode,width in enumerate(default_widths[:6]):
            for raw in args.board_request_raw:
                values=(raw,mode,2,0xa55a,*default_centers,width)
                accesses=original_post(values)
                post_cases.append((values,accesses))
                gap_post_cases.append(dict(requested_raw=raw,mode=mode,selector=2,
                    writes=[dict(address=hex(a),value=hex(v)) for op,a,v in accesses if op==1]))
    def original_publish(values):
        flag1,flag2,word,index,mutation=values
        class Publish(Native):
            def observe(self,cpu,access,a,size,v,ctx):
                assert size==2 and a in (0xb4d2,0xb52c,0xb4d8,0xb4dc)
                self.accesses.append((1,a,v&65535))
        n=Publish(image,[]);n.accesses=[]
        for a,v in [(0xb4ee,flag1),(0xb4f2,flag2),(0xb4d2,word),(0xb550,index),(0xb52c,0xa55a)]:n.put16(a,v)
        n.cpu.hook_add(UC_HOOK_MEM_READ,lambda cpu,access,a,size,v,ctx:
            n.accesses.append((0,a,int.from_bytes(cpu.mem_read(a,size),'little'))))
        rules=[(name,definitions['MATCH_'+name],definitions['MASK_'+mask])
            for name,mask in [('EXTHZ','PALUS'),('BSET','PALU2'),('BNEM1','BNEM1')]]
        pc=0x616e
        for _ in range(100):
            if pc==0x6200:return n.accesses
            if pc==0xacc:
                n.accesses.append((2,pc,0))
                if mutation:
                    n.put16(0xb4d2,int.from_bytes(n.cpu.mem_read(0xb4d2,2),'little')^0x8000)
                    n.put16(0xb4f2,1)
                pc=n.cpu.reg_read(X[1]);n.cpu.reg_write(PC,pc);continue
            word=int.from_bytes(n.cpu.mem_read(pc,4),'little')
            match=next((name for name,pattern,mask in rules if word&3==3 and word&mask==pattern),None)
            if match:
                rd=(word>>7)&31;rs1=(word>>15)&31;rs2=(word>>20)&31
                value=n.cpu.reg_read(X[rs1]) if rs1 else 0;next_pc=pc+4;result=None
                if match=='EXTHZ':result=value&65535
                elif match=='BSET':result=value|(((1<<(((word>>25)&31)+1))-1)<<rs2)
                else:
                    disp=((word>>31)<<12)|(((word>>7)&1)<<11)|(((word>>25)&63)<<5)|(((word>>8)&15)<<1)
                    if value!=(signed(rs2,5)&0xffffffff):next_pc=pc+signed(disp,13)
                if result is not None and rd:n.cpu.reg_write(X[rd],result&0xffffffff)
                n.cpu.reg_write(PC,next_pc)
            else:n.cpu.emu_start(pc,0x7ffffffe,count=1)
            pc=n.cpu.reg_read(PC)
        raise AssertionError('RXON caller publish budget exceeded')
    publish_cases=[]
    for flag1 in (0,1,2,65535):
        for flag2 in (0,1,2,65535):
            for word in (0,0xa55a,65535):
                for index in (0,3,65535):
                    for mutation in (0,1):
                        values=(flag1,flag2,word,index,mutation)
                        publish_cases.append((values,original_publish(values)))
    def original_timing(values):
        timer,busy_reads,index_first,index_last,frame,unused,high,low=values
        class Timing(Native):
            def observe(self,cpu,access,a,size,v,ctx):
                assert (a==0x500901f0 and size==4) or (0x928c<=a<0x92b4 and size==4) or (a==0x92ce and size==2),(hex(a),size)
                self.accesses.append((1+(2 if size==4 else 0),a,v&((1<<(8*size))-1)))
        n=Timing(image,[]);n.accesses=[];n.timer_reads=n.index_reads=0
        n.cpu.mem_map(0x50090000,0x1000)
        for a,v in [(0x50090104,frame),(0x500900b8,unused),(0x500900bc,high),(0x500900c0,low)]:
            n.cpu.mem_write(a,struct.pack('<I',v))
        def timing_read(cpu,access,a,size,v,ctx):
            if a==0x500901f0:
                n.timer_reads+=1
                n.cpu.mem_write(a,struct.pack('<I',timer|(0x100000 if n.timer_reads<=busy_reads else 0)))
            elif a==0x92ce:
                n.put16(a,index_last if n.index_reads else index_first);n.index_reads+=1
            n.accesses.append((2 if size==4 else 0,a,int.from_bytes(cpu.mem_read(a,size),'little')))
        n.cpu.hook_add(UC_HOOK_MEM_READ,timing_read)
        rules=[(name,definitions['MATCH_'+name],definitions['MASK_'+mask])
            for name,mask in [('EXTHZ','PALUS'),('BCLR','PALU2'),('SWRR','PALU'),('HWLP_SETUP','HWLP_SETUP')]]
        pc=0xad0;loop=None
        for _ in range(200):
            if pc==0xb52:return n.accesses
            executed=pc;word=int.from_bytes(n.cpu.mem_read(pc,4),'little')
            match=next((name for name,pattern,mask in rules if word&3==3 and word&mask==pattern),None)
            if match:
                rd=(word>>7)&31;rs1=(word>>15)&31;rs2=(word>>20)&31
                value=n.cpu.reg_read(X[rs1]) if rs1 else 0;next_pc=pc+4
                if match=='EXTHZ':n.cpu.reg_write(X[rd],value&65535)
                elif match=='BCLR':
                    mask=((1<<(((word>>25)&31)+1))-1)<<rs2
                    n.cpu.reg_write(X[rd],value&~mask&0xffffffff)
                elif match=='SWRR':
                    a=(value+n.cpu.reg_read(X[rd]))&0xffffffff;v=n.cpu.reg_read(X[rs2])
                    n.accesses.append((3,a,v));n.cpu.mem_write(a,struct.pack('<I',v))
                else:
                    assert pc==0xae8 and value==10 and word==0x008740fb
                    loop=[pc+4,pc+((word>>20)<<1),value]
                n.cpu.reg_write(PC,next_pc)
            else:n.cpu.emu_start(pc,0x7ffffffe,count=1)
            pc=n.cpu.reg_read(PC)
            if loop and executed==loop[1]:
                loop[2]-=1
                if loop[2]:pc=loop[0];n.cpu.reg_write(PC,pc)
        raise AssertionError('RXON timing budget exceeded')
    timing_cases=[]
    for timer in (0,23,24,0x1ffff,0xffffffff):
        for busy_reads in (0,1,9,10):
            for index in range(5):
                values=(timer,busy_reads,index,(index+2)%5,0x12345678,0xaabbccdd,0xabcdef12,0x76543210)
                expected=original_timing(values)
                assert sum(a==0x500901f0 and op==2 for op,a,v in expected)==(10 if timer&0x100000 else min(busy_reads+1,10))
                timing_cases.append((values,expected))
    def native_decode_word(word,auxiliary=None):
        n=Native(image,[]);n.put16(0x30050,word)
        if auxiliary is not None:n.put16(0x30054,auxiliary)
        pc=0x602c
        for step in range(60):
            if pc==0x6080 and auxiliary is None:return struct.unpack('<5H',n.cpu.mem_read(0xb530,10))
            if pc==0x609e and auxiliary is not None:
                context=bytes(n.cpu.mem_read(0xb530,0x22))
                return tuple(struct.unpack_from('<H',context,o)[0] for o in (0,4,8,0x20,0x14,0x16))
            opcode=int.from_bytes(n.cpu.mem_read(pc,4),'little')
            rd=(opcode>>7)&31;rs1=(opcode>>15)&31
            if opcode&definitions['MASK_PALUS']==definitions['MATCH_EXTHZ']:
                n.cpu.reg_write(X[rd],n.cpu.reg_read(X[rs1])&65535);n.cpu.reg_write(PC,pc+4)
            elif opcode&definitions['MASK_PALU2']==definitions['MATCH_EXTRACTU']:
                value=(n.cpu.reg_read(X[rs1])>>((opcode>>20)&31))&((1<<(((opcode>>25)&31)+1))-1)
                n.cpu.reg_write(X[rd],value);n.cpu.reg_write(PC,pc+4)
            elif opcode&definitions['MASK_PALU2']==definitions['MATCH_BCLR']:
                mask=((1<<(((opcode>>25)&31)+1))-1)<<((opcode>>20)&31)
                n.cpu.reg_write(X[rd],n.cpu.reg_read(X[rs1])&~mask&0xffffffff);n.cpu.reg_write(PC,pc+4)
            else:n.cpu.emu_start(pc,0x7ffffffe,count=1)
            pc=n.cpu.reg_read(PC)
        raise AssertionError('native parameter decode budget')
    decode_cases=[]
    for selector in (0,4,15,20):
        for mode in range(6):
            for port in range(16):
                word=(selector<<8)|(port<<4)|mode
                values=native_decode_word(word)
                assert (values[0],values[2],values[4])==(mode,port,selector)
                decode_cases.append((word,mode,port,selector))
    auxiliary_cases=[]
    for selector in (2,4,6,15):
        for mode in (1,5,6):
            for correction_index in range(4):
                for slot in (0,7,14,15):
                    for control in (0,0x50,0xfff):
                        word=(correction_index<<13)|(selector<<8)|(2<<4)|mode
                        auxiliary=(slot<<12)|control
                        expected=native_decode_word(word,auxiliary)
                        assert expected==(mode,2,selector,correction_index,slot,control)
                        auxiliary_cases.append((word,auxiliary,expected))
    route_chain=None;route_dependencies=[]
    if args.runtime_snapshot:
        from elftools.elf.elffile import ELFFile
        from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB
        from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_SP,UC_ARM_REG_PC
        from sdr.rf_frontend import decode_row
        runtime_path=args.runtime_snapshot.resolve();frontend_path=args.frontend_snapshot.resolve()
        runtime=json.loads(runtime_path.read_text(encoding='utf-8'));frontend=json.loads(frontend_path.read_text(encoding='utf-8'))
        assert runtime['status']==frontend['status']=='passed'
        assert runtime['stable_repeated_reads'] and frontend['stable_repeated_reads']
        assert runtime['epoch']==frontend['epoch']
        nv_path=ROOT/frontend['artifacts'][0]['path'];nv=nv_path.read_bytes()
        assert sha(nv_path)==frontend['artifacts'][0]['sha256']
        for artifact in runtime['artifacts']:
            path=ROOT/artifact['path'];assert sha(path)==artifact['sha256'];route_dependencies.append(path)
        assert nv[:0x180]==(ROOT/runtime['artifacts'][0]['path']).read_bytes()
        cp_path=image_path.with_name('cp.bin');axf_path=image_path.with_name('cp.axf');blob=cp_path.read_bytes()
        assert sha(cp_path)==runtime['firmware']['cp_baseline_sha256']
        with axf_path.open('rb') as stream:
            elf=ELFFile(stream);symbol=elf.get_section_by_name('.symtab').get_symbol_by_name('xcvr_rxon')[0]
            section=elf.get_section(symbol['st_shndx']);offset=(symbol['st_value']&~1)-section['sh_addr']
            prefix=section.data()[offset:offset+46]
        offsets=[];offset=blob.find(prefix)
        while offset>=0:offsets.append(offset);offset=blob.find(prefix,offset+1)
        assert len(offsets)==2
        route_rows=[];board_request_cases=0
        for row in runtime['rows']:
            if row['raw_band_id'] not in (3,5,8,40):continue
            nv_row=row['nv_row'];selector=row['selector_from_native_evidence'];port=row['rx_port']
            assert 0<=nv_row<24 and port is not None and port<8
            decoded_nv=decode_row(nv,nv_row,0)
            assert decoded_nv['rx_port']==port
            samples=[]
            for bw in (0,5):
                for at in offsets:
                    cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB);cpu.mem_map(0x80000000,0x1000000);cpu.mem_write(0x801ab000,blob)
                    cpu.mem_write(0x804ed5ac+4,struct.pack('<H',nv_row));cpu.mem_write(0x804ed5ac+6,bytes([selector]))
                    cpu.mem_write(0x804ed5f8+28,struct.pack('<H',bw));cpu.mem_write(0x804f42b8,nv)
                    cpu.mem_write(0x80900008,struct.pack('<I',0x80901000))
                    cpu.reg_write(UC_ARM_REG_R0,0x80900000);cpu.reg_write(UC_ARM_REG_SP,0x80910000)
                    cpu.emu_start((0x801ab000+at)|1,0x801ab000+at+42,count=100)
                    assert cpu.reg_read(UC_ARM_REG_PC)==0x801ab000+at+42
                    packed=int.from_bytes(cpu.mem_read(0x80901000,4),'little')
                    assert packed==0x500000|(selector<<8)|(port<<4)|bw
                    values=native_decode_word(packed&65535)
                    assert (values[0],values[2],values[4])==(bw,port,selector)
                    extended=native_decode_word(packed&65535,packed>>16)
                    assert extended[4:]==(0,0x50)
                    table_index=15*selector+extended[4]
                    table_addresses=(0x8764+2*table_index,0x9438+2*table_index,
                                     0xaf78+4*table_index,0xaf7a+4*table_index)
                    samples.append(dict(bandwidth=bw,cp_entry=hex(0x801ab000+at),packed=hex(packed),rf_context_field4=values[2],
                        rf_auxiliary=hex(packed>>16),rf_context_slot=extended[4],rf_context16=hex(extended[5]),
                        shared_table_index=table_index,shared_table_addresses=[hex(a) for a in table_addresses],
                        shared_table_image_values=[hex(struct.unpack_from('<H',image,a)[0]) if a+2<=len(image) else None for a in table_addresses],
                        shared_table_value_scope='Values outside retained RF binary are unknown runtime RAM, not zero/default calibration.'))
            group='B' if selector<=12 or selector==17 else 'A'
            table=0x8a54 if group=='B' else 0x84f0;stride=10 if group=='B' else 8
            words=struct.unpack_from('<'+('5H' if group=='B' else '4H'),image,table+stride*port)
            destinations=[0x30418,0x3040c,0x3049c,0x30480,0x30414] if group=='B' else [0x304c0,0x30480,0x30430,0x30414]
            applied_cases=[]
            frequency_pairs=[]
            first_mmio_by_mode={}
            if group=='B':
                for mode in range(6):
                    for raw in (args.board_request_raw or (6812500,8815000)):
                        request=(mode|(port<<4)|(selector<<8),0x50,raw,0,0,7)
                        # Zero analog/digital flags and reset register fixture;
                        # this proves application, not unknown runtime flags.
                        values=(mode,selector,port,0,0,7,0,0xffffffff)
                        trace,stages=original_full(values,True,0,True,0,0x50,request,True)
                        # Compare actual ordered MMIO writes, retaining duplicates
                        # and latch operations. Do not infer filter bit semantics.
                        mmio=[(op,a,v) for op,a,v in trace
                              if op in (1,3) and 0x30000<=a<0x33000]
                        if mode not in first_mmio_by_mode:
                            first_mmio_by_mode[mode]=(raw,mmio)
                        else:
                            first_raw,first_mmio=first_mmio_by_mode[mode]
                            same_order=[(op,a) for op,a,v in mmio]==[(op,a) for op,a,v in first_mmio]
                            differences=[]
                            if same_order:
                                differences=[dict(write_index=i,address=hex(a),bytes=2 if op==1 else 4,
                                                  first_value=hex(v0),second_value=hex(v))
                                             for i,((op,a,v),(_,_,v0)) in enumerate(zip(mmio,first_mmio)) if v!=v0]
                            frequency_pairs.append(dict(mode=mode,first_requested_raw=first_raw,
                                second_requested_raw=raw,first_write_count=len(first_mmio),second_write_count=len(mmio),
                                same_ordered_addresses_and_widths=same_order,value_differences=differences,
                                scope='Native B request through0x5360 with actual shared helpers and synthetic initial MMIO; excludes caller post-configure and analog hardware.'))
                        writes={a:v for op,a,v in trace if op==1}
                        assert writes[0x30480]==words[3]
                        assert writes[0x30468]==struct.unpack_from('<H',image,0x8184+2*port)[0]
                        for index,address in ((0,0x30418),(1,0x3040c)):
                            assert writes[address]==words[index],(row['raw_band_id'],mode,hex(address),writes[address],words[index])
                        latch_writes=[v for op,a,v in trace if op==1 and a==0x30414]
                        assert latch_writes==[words[4],words[4]|0x40,words[4]|0x60],latch_writes
                        request_cases.append((request,trace,stages,initial_cells(trace)))
                        board_request_cases+=1
                        applied_cases.append(dict(mode=mode,requested_raw=raw,
                            latch_30414_writes=[hex(v) for v in latch_writes],
                            analog_writes={hex(a):hex(writes[a]) for a in (0x30418,0x3040c,0x30480,0x30414,0x30468)}))
            route_rows.append(dict(raw_band_id=row['raw_band_id'],nv_row=nv_row,rx_port=port,selector=selector,group=group,
                retained_default_B_request_application=applied_cases,
                paired_frequency_mmio_differences=frequency_pairs,
                cp_pack_and_rf_decode=samples,analog_table_base=hex(table),analog_row_stride=stride,
                binary_default_analog_fields=[dict(offset=2*i,word=hex(word),destination=hex(destinations[i])) for i,word in enumerate(words)],
                shared_30468_word=hex(struct.unpack_from('<H',image,0x8184+2*port)[0]),
                rffe_switch_open=decoded_nv['mipi']['switch_open'],
                rffe_lna_open=decoded_nv['mipi']['lna_open']))
        assert len(route_rows)==4
        route_chain=dict(snapshot=runtime_path.relative_to(ROOT).as_posix(),frontend=frontend_path.relative_to(ROOT).as_posix(),
            retained_default_B_request_cases=board_request_cases,
            epoch=runtime['epoch'],rows=route_rows,
            scope='Actual retained board NV port -> native CP pack prefix in both variants -> native RF decode -> binary default analog row. RFAD delivery and live RF RAM table contents not observed.',
            distinction='Analog rows are values in retained RF binary, not live RAM/calibration readback; board FEM identity and physical pin wiring remain unknown.',
            row_application='Destinations identify native consumers, not unconditional final values: masks/OR/latch apply; A30430 may instead use84b0 under runtime flag92cc.',
            B_group_row_offset6_used_by_enter=True,hardware_written=False)
        route_dependencies.extend([runtime_path,frontend_path,nv_path,cp_path,axf_path,ROOT/'tools/sdr/rf_frontend.py',ROOT/'tools/sdr/rf_runtime.py'])
    build=ROOT/'work/rf-prepare-b-prefix';build.mkdir(exist_ok=True)
    source=ROOT/'firmware/rf_rebuild/rf_core_rxon_prepare_b_prefix.c'
    middle_source=ROOT/'firmware/rf_rebuild/rf_core_rxon_prepare_b_mode.c'
    full_source=ROOT/'firmware/rf_rebuild/rf_core_rxon_b.c'
    decode_source=ROOT/'firmware/rf_rebuild/rf_core_rxon_request.c'
    harness=ROOT/'tools/verify/rf_prepare_b_prefix_harness.c'
    gcc=sdk/'prebuilts/win32/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
    binaries=[];builds=[]
    for opt in ('-O0','-O2'):
        binary=build/(opt[1:]+'.elf');binaries.append(binary)
        subprocess.run([str(gcc),'-mcpu=cortex-a5','-mthumb',opt,'-ffreestanding','-fno-builtin',
            '-nostdlib','-Wl,--build-id=none','-Wl,-Ttext=0x100000','-Wl,-e,verify_prepare_b',
            str(source),str(middle_source),str(full_source),str(decode_source),str(ROOT/'firmware/rf_rebuild/rf_core_rxon_finish.c'),
            *[str(ROOT/'firmware/rf_rebuild'/name) for name in ('rf_core_tune_flow.c','rf_core_tune_plan.c','rf_core_frequency.c','rf_core_mode.c')],
            str(harness),'-lgcc','-o',str(binary)],check=True,capture_output=True)
        replica=Replica(binary)
        def call_integrated(initial,fail_at=0,name='verify_rxon_integrated'):
            assert len(initial)<=256
            replica.cpu.mem_write(0x218000,b''.join(struct.pack('<2I',*cell) for cell in initial))
            # Stateful address lookup costs more test instructions than the
            # small slice harnesses; retain their default budget unchanged.
            replica.cpu.mem_write(0x210000,struct.pack('<3I',0x218000,len(initial),fail_at))
            replica.cpu.mem_write(0x210100,b'\xa5'*4620)
            replica.cpu.reg_write(UC_ARM_REG_R0,0x210000);replica.cpu.reg_write(UC_ARM_REG_R1,0x210100)
            replica.cpu.reg_write(UC_ARM_REG_SP,0x20f000);replica.cpu.reg_write(UC_ARM_REG_LR,0x70000000)
            replica.cpu.emu_start(replica.symbols[name]|1,0x70000000,count=1000000)
            assert replica.cpu.reg_read(UC_ARM_REG_PC)==0x70000000,'integrated harness instruction budget'
            result=replica.cpu.reg_read(UC_ARM_REG_R0);raw=bytes(replica.cpu.mem_read(0x210100,4620))
            code,calls,count=struct.unpack_from('<iII',raw)
            assert result==code&0xffffffff and count<=384
            return code,calls,list(struct.iter_unpack('<3I',raw[12:12+12*count]))
        for values,slot,control,expected,stages,initial in integrated_cases:
            actual=call_integrated(initial)
            assert actual==(0,len(expected),expected),('integrated',opt,values,slot,actual,expected)
        for missing in range(3):
            result,raw=replica.call('verify_rxon_integrated_invalid',struct.pack('<3I',0,missing,0),4620)
            assert result==0xffffffff and struct.unpack_from('<iII',raw)==(-1,0,0)
        integrated_faults=0
        for values,slot,control,expected,stages,initial in integrated_cases:
            if values[1]!=4 or values[0] not in (0,5):continue
            for at in range(1,len(expected)+1):
                actual=call_integrated(initial,at)
                assert actual==(stages[at-1],at,expected[:at-1]),('integrated failure',opt,values,at,actual,stages[at-1])
                integrated_faults+=1
        request_faults=0
        for request,expected,stages,initial in request_cases:
            actual=call_integrated(initial,name='verify_rxon_request_integrated')
            assert actual==(0,len(expected),expected),('request integrated',opt,request,actual,expected)
            if (request[0]&0x1f00)!=0x400 or (request[0]&15) not in (0,5) or request[2]!=6812500:continue
            for at in range(1,len(expected)+1):
                actual=call_integrated(initial,at,'verify_rxon_request_integrated')
                assert actual==(stages[at-1],at,expected[:at-1]),('request failure',opt,request,at,actual,stages[at-1])
                request_faults+=1
        invalid_requests=0
        def request_initial(word,aux=0):
            return [(0x30050,word),(0x30054,aux),(0x30058,0),(0x30008,0)]
        for word,aux in ((6,0),(13<<8,0),(0,15<<12)):
            actual=call_integrated(request_initial(word,aux),name='verify_rxon_request_integrated')
            assert actual==(-1,4,[(0,a,v) for a,v in request_initial(word,aux)]),('invalid request',actual)
            invalid_requests+=1
        # Later invalid values must stop without rollback, after context stores.
        for bad in ('zfif','factor'):
            request,expected,stages,initial=request_cases[1] if bad=='factor' else request_cases[0]
            initial=dict(initial)
            if bad=='zfif':initial[0xb4de]=4;stop=next(i for i,x in enumerate(expected) if x[:2]==(0,0xb550))+1
            else:
                initial[0xa710]=1;initial[0x940c+2*((request[0]>>8)&31)]=2;initial[0xa718]=0
                # The selected case already exercises state1.
                stop=next(i for i,x in enumerate(expected) if x[:2]==(0,0xb526))+1
            actual=call_integrated(sorted(initial.items()),name='verify_rxon_request_integrated')
            assert actual[0]==-1 and actual[1]==stop,('late invalid',bad,actual,stop)
            assert any(op==1 and a==0xb530 for op,a,v in actual[2])
            invalid_requests+=1
        def call_timing(values,fail_at=0):
            result,raw=replica.call('verify_rxon_timing',struct.pack('<9I',*values,fail_at),492)
            code,calls,count=struct.unpack_from('<iII',raw)
            assert result==code&0xffffffff and count<=40
            return code,calls,list(struct.iter_unpack('<3I',raw[12:12+12*count]))
        for values,expected in timing_cases:
            assert call_timing(values)==(0,len(expected),expected),('timing',opt,values,call_timing(values),expected)
        timing_faults=0
        for values,expected in timing_cases:
            if values[0]!=0x1ffff or values[2]!=4:continue
            for at in range(1,len(expected)+1):
                assert call_timing(values,at)==(-2,at,expected[:at-1])
                timing_faults+=1
        def call_publish(values,fail_at=0):
            result,raw=replica.call('verify_rxon_publish',struct.pack('<6I',*values,fail_at),492)
            code,calls,count=struct.unpack_from('<iII',raw)
            assert result==code&0xffffffff and count<=40
            return code,calls,list(struct.iter_unpack('<3I',raw[12:12+12*count]))
        for values,expected in publish_cases:
            assert call_publish(values)==(0,len(expected),expected),('publish',opt,values,call_publish(values),expected)
        for missing in range(4):
            result,raw=replica.call('verify_rxon_publish_invalid',struct.pack('<6I',missing,0,0,0,0,0),492)
            assert result==0xffffffff and struct.unpack_from('<iII',raw)==(-1,0,0)
        publish_faults=0
        for values,expected in publish_cases:
            if values[2:4]!=(0xa55a,3):continue
            for at in range(1,len(expected)+1):
                error=-3 if expected[at-1][0]==2 else -2
                assert call_publish(values,at)==(error,at,expected[:at-1])
                publish_faults+=1
        def call_post(values,fail_at=0):
            data=(*values[:4],fail_at,*values[4:])
            result,raw=replica.call('verify_rxon_post',struct.pack('<10I',*data),492)
            code,calls,count=struct.unpack_from('<iII',raw)
            assert result==code&0xffffffff and count<=40
            return code,calls,list(struct.iter_unpack('<3I',raw[12:12+12*count]))
        for values,expected in post_cases:
            actual=call_post(values)
            assert actual==(0,len(expected),expected),('post-RX',opt,values,actual,expected)
        post_faults=0
        for values,expected in post_cases:
            if values[0]!=6812500 or values[1] not in (0,4) or values[2] not in (1,4,5):continue
            for at in range(1,len(expected)+1):
                assert call_post(values,at)==(-2,at,expected[:at-1])
                post_faults+=1
        invalid=call_post((6812500,7,4,0,*default_centers,0))
        assert invalid==(-1,0,[])
        def call(field,factor,initial,fail_at=0):
            result,raw=replica.call('verify_prepare_b',struct.pack('<4I',field,factor,initial,fail_at),492)
            code,calls,count=struct.unpack_from('<iII',raw)
            assert result==code&0xffffffff and count<=40
            return code,calls,list(struct.iter_unpack('<3I',raw[12:12+12*count]))
        for field,factor,initial,expected in cases:
            code,calls,actual=call(field,factor,initial)
            assert (code,calls,actual)==(0,len(expected),expected),(opt,field,factor,initial,actual,expected)
        faults=0
        for at in range(1,27):
            code,calls,actual=call(3,9,0xa55a,at)
            expected=original(3,9,0xa55a)
            assert code==-2 and calls==at and actual==expected[:at-1]
            faults+=1
        def call_early(name,values,fail_at=0):
            result,raw=replica.call(name,struct.pack('<4I',*values,fail_at),492)
            code,calls,count=struct.unpack_from('<iII',raw)
            assert result==code&0xffffffff and count<39
            saved=struct.unpack_from('<2I',raw,12+39*12)
            return code,calls,list(struct.iter_unpack('<3I',raw[12:12+count*12])),saved
        for values,expected in enter_cases:
            code,calls,actual,saved=call_early('verify_prepare_b_enter',values)
            assert (code,calls,actual)==(0,len(expected),expected)
            assert saved==(values[2],values[2]^65535)
        early_faults=0
        for flag in (0,1):
            values=(3,flag,0xa55a);expected=original_enter(*values)
            for at in range(1,len(expected)+1):
                code,calls,actual,saved=call_early('verify_prepare_b_enter',values,at)
                assert code==-2 and calls==at and actual==expected[:at-1]
                assert saved==(0x1234,0x5678)
                early_faults+=1
        code,calls,actual,_=call_early('verify_prepare_b_commit',(0,0,0))
        assert (code,calls,actual)==(0,6,commit_expected)
        for at in range(1,7):
            code,calls,actual,_=call_early('verify_prepare_b_commit',(0,0,0),at)
            assert code==-2 and calls==at and actual==commit_expected[:at-1]
        clock_faults=0
        for values,expected in clock_cases:
            code,calls,actual,_=call_early('verify_clock_mode',values)
            assert (code,calls,actual)==(0,len(expected),expected),(values,actual,expected)
            for at in range(1,len(expected)+1):
                code,calls,actual,_=call_early('verify_clock_mode',values,at)
                assert code==-2 and calls==at and actual==expected[:at-1]
                clock_faults+=1
        tables_faults=0
        for values,expected in tables_cases:
            for fail_at in ([0]+list(range(1,len(expected)+1)) if values==(6,4,7,0x1234) else [0]):
                result,raw=replica.call('verify_rxon_tables',struct.pack('<5I',*values,fail_at),1548)
                code,calls,count=struct.unpack_from('<iII',raw)
                actual=list(struct.iter_unpack('<3I',raw[12:12+count*12]))
                assert result==code&0xffffffff
                if fail_at:
                    assert code==-2 and calls==fail_at and actual==expected[:fail_at-1]
                    tables_faults+=1
                else:assert code==0 and calls==len(expected) and actual==expected,(values,actual,expected)
        def call_middle(values,fail_at=0):
            result,raw=replica.call('verify_prepare_b_mode',struct.pack('<7I',*values,fail_at),492)
            code,calls,count=struct.unpack_from('<iII',raw)
            assert result==code&0xffffffff and count<=40
            return code,calls,list(struct.iter_unpack('<3I',raw[12:12+12*count]))
        for values,expected in middle_cases:
            code,calls,actual=call_middle(values)
            assert (code,calls,actual)==(0,len(expected),expected),(opt,values,actual,expected)
        middle_faults=0
        # Exercise each distinct access path, including mode6 and selector5/15.
        for values,expected in middle_cases:
            if values[4]!=0xa55a or values[1] not in (4,5,15) or values[0] not in (0,1,3,4,6):continue
            for at in range(1,len(expected)+1):
                code,calls,actual=call_middle(values,at)
                assert code==-2 and calls==at and actual==expected[:at-1],(values,at)
                middle_faults+=1
        builds.append(dict(optimization=opt,native_comparisons=len(cases),all_bus_failure_positions=faults))
        builds[-1].update(middle_native_comparisons=len(middle_cases),middle_bus_failure_cases=middle_faults)
        builds[-1].update(enter_native_comparisons=len(enter_cases),enter_bus_failure_cases=early_faults,
                          coefficient_commit_native_comparisons=1,commit_bus_failure_cases=6)
        builds[-1].update(clock_helper_native_comparisons=len(clock_cases),clock_bus_failure_cases=clock_faults)
        builds[-1].update(shared_table_native_comparisons=len(tables_cases),shared_table_bus_failure_cases=tables_faults)
        def call_full(values,fail_at=0):
            data=(*values[:7],fail_at,values[7])
            result,raw=replica.call('verify_rxon_b',struct.pack('<9I',*data),1548)
            code,calls,count=struct.unpack_from('<iII',raw)
            assert result==code&0xffffffff and count<=128
            return code,calls,list(struct.iter_unpack('<3I',raw[12:12+count*12]))
        for values,expected in full_cases:
            code,calls,actual=call_full(values)
            assert (code,calls,actual)==(0,len(expected),expected),(opt,values,actual,expected)
        full_faults=0
        for mode in (0,3,4,6):
            for analog,digital in ((0,0),(1,2)):
                values=(mode,5,3,analog,digital,9,0xa55a,2)
                expected=original_full(values)
                for at in range(1,len(expected)+1):
                    code,calls,actual=call_full(values,at)
                    failed_op=expected[at-1][0]
                    expected_error=-3 if failed_op==2 else -4 if failed_op==3 else -2
                    assert code==expected_error and calls==at and actual==expected[:at-1],(values,at,code)
                    full_faults+=1
        builds[-1].update(composed_body_native_comparisons=len(full_cases),composed_bus_and_callback_failure_cases=full_faults)
        for word,mode,port,selector in decode_cases:
            result,raw=replica.call('rf_core_decode_rxon_request',struct.pack('<13H',word,*([0]*12)),20)
            actual=struct.unpack('<2I6H',raw)
            assert result==0 and (actual[2],actual[3],actual[4])==(mode,port,selector),('RF port field mismatch',word,actual)
        for word,auxiliary,expected in auxiliary_cases:
            result,raw=replica.call('rf_core_decode_rxon_request',struct.pack('<13H',word,auxiliary,*([0]*11)),20)
            actual=struct.unpack('<2I6H',raw)
            assert result==0 and actual[2:]==expected,('auxiliary/index decode mismatch',hex(word),hex(auxiliary),actual[2:],expected)
        builds[-1]['auxiliary_decode_native_comparisons']=len(auxiliary_cases)
        builds[-1]['parameter_decode_native_comparisons']=len(decode_cases)
        builds[-1].update(post_rx_native_comparisons=len(post_cases),post_rx_failure_positions=post_faults,
                          post_rx_invalid_mode_no_io=True)
        builds[-1].update(publish_native_comparisons=len(publish_cases),publish_failure_positions=publish_faults,
                          publish_invalid_contract_no_io_cases=4)
        builds[-1].update(timing_native_comparisons=len(timing_cases),timing_failure_positions=timing_faults)
        builds[-1].update(integrated_B_native_comparisons=len(integrated_cases),integrated_B_failure_positions=integrated_faults,
                          integrated_B_invalid_bus_no_io_cases=3)
        builds[-1].update(request_B_native_comparisons=len(request_cases),request_B_failure_positions=request_faults,
                          request_B_invalid_cases=invalid_requests)
    dependencies=[Path(__file__),source,source.with_suffix('.h'),source.with_name('rf_core_rxon_prepare.h'),
        harness,middle_source,middle_source.with_suffix('.h'),full_source,full_source.with_suffix('.h'),decode_source,decode_source.with_suffix('.h'),image_path,header,manifest,ROOT/'tools/verify/verify_rf_frequency_native.py',
        ROOT/'tools/verify/verify_rf_mode_native.py',*binaries,*route_dependencies]
    dependencies += [ROOT/'firmware/rf_rebuild/rf_core_rxon_finish.c',ROOT/'firmware/rf_rebuild/rf_core_rxon_finish.h']
    dependencies += [ROOT/'firmware/rf_rebuild'/name for name in ('rf_core_tune_flow.c','rf_core_tune_flow.h','rf_core_tune_plan.c','rf_core_tune_plan.h','rf_core_frequency.c','rf_core_frequency.h')]
    dependencies += [header.with_name(name) for name in ('riscv-opc.c','ri5cy_user_manual.pdf')]
    dependencies += [ROOT/'firmware/rf_rebuild/rf_core_mode.c',ROOT/'firmware/rf_rebuild/rf_core_mode.h']
    report=dict(status='passed',recorded_at=datetime.now().astimezone().isoformat(),device_accessed=False,
        deployed=False,firmware_changed=False,native_entry='0x4fc4',native_stop='0x50da',
        scope='B RXON body bus/callback composition and native coefficient-before-dispatch order; synthetic states, shared cal/mode internals abstracted; not cold-start or PLL proof.',
        reads_per_case=15,writes_per_case=11,modeled_extensions=['EXTHZ'],builds=builds,
        analog_table=dict(base='0x8a54',stride=10,field='rxon_context+4',offsets=[0,2,4,8]),
        shared_table=dict(base='0x8184',stride=2),
        native_b_enter=dict(entry='0x4ecc',stop='0x4f90',cases=len(enter_cases),
            captured_registers=['0x30400','0x30404'],digital_flag='0xb52a nonzero preserves30480 by OR',
            analog_table_offset=6,excluded_prologue='ABI save trampoline4ec8',
            next_step='load mode and call0x4632 at4f94; clock helper independently reconstructed and tested'),
        native_clock_helper=dict(entry='0x4632',jump_table='0x7ba4',cases=len(clock_cases),
            modeled_extensions=['LWRR','BNEM1','BEQM1'],
            hardware_time_preserved=False,register='0x30350 BBPLL2_REGA',
            result='Native reads/writes/order preserved; native NOPs not a cross-core timing guarantee.'),
        composed_b_body=dict(entry='0x4ecc',stop='0x5360',cases=len(full_cases),
            calibration_and_mode_internals_executed=False,
            callback_contract='Native calls453c and3a7c intercepted, same semantic callbacks in ARM harness; order/arguments/error stop tested.',
            calibration_can_update_mode=True,coefficient_generation_in_body=False,
            cold_start_replaced=False,hardware_tested=False,
            limitations=['Excludes RF ABI save/restore trampolines.',
                'Requires coefficients already produced for this request; producer synchronization not provided.',
                'Native callback timing and actual MMIO/PLL behavior not emulated.'],
            sample_accesses=[dict(operation={0:'read16',1:'write16',2:'calibration_callback',3:'mode_callback'}[op],
                address=hex(a),value=hex(v)) for op,a,v in full_cases[0][1]]),
        native_b_feedback_consumption=dict(entry='0x4ecc',stop='0x5360',
            shared_helpers_executed=['0x453c','0x3a7c'],cases=feedback_cases,
            paired_status_words=[0,65535],status_addresses=['0x3036c','0x3037c'],
            control_writes=[dict(address='0x30364',value='0x33'),dict(address='0x30364',value='0xb3')],
            result='In these B RXON contexts the full body including shared helpers neither reads calibration status nor changes its operations based on externally supplied ready/VCO bits.',
            scope='36 original instruction executions; mode0..5, B3/B5/B8 port fixtures, zero software analog/digital flags. No ABI prologue/epilogue, caller tail, autonomous hardware calibration or PLL lock model.',
            no_wait_added=True,physical_cutoff_proved=False),
        coefficient_producer_dispatch=dict(entry='0x6122',coefficient_call='0x6134 ->0x37f0',
            output='0xb520',working_source='0xb53c',context='0xb530',cases=dispatch_cases,
            B_call='0x6158 ->0x4ec8',A_call='0x614a ->0x46f6',
            software_order_proved=True,hardware_request_freshness_proved=False,
            limitation='Original software computes then dispatches synchronously; synthetic caller inputs do not prove RFAD delivery or current-request identity on hardware.'),
        shared_post_rx=dict(entry='0x38a8',RXON_call='0x616a',retune_call='0x66ce',
            focused_B3_gap_cases=gap_post_cases,
            cases=len(post_cases),default_centers_raw=default_centers,default_widths_raw=default_widths,
            runtime_reads=['0x32004:16','0xb538:16','0x8530..0x853c:32','0x91a0+4*mode:32'],
            writes=['0x50109050:32','0x3033c:16','0x30340:16','0x3030c:16','0x30310:16','0x32004:16'],
            lowband_same_default_branch=[6812500,6875000],
            result='Original request-frequency profile selection; preserves runtime table reads and short-circuit order. No ready/VCO reads or LO-lock check.',
            deployed=False,hardware_meaning_confirmed=False,physical_limits_proved=False),
        caller_publish_state=dict(entry='0x616e',stop='0x6200',cases=len(publish_cases),
            conditional_flags=['0xb4ee ==1: b4d2 OR0x10 then0xacc','0xb4f2 ==1: b4d2 OR0x20 then0xacc'],
            final_stores=['b52c=1','read b52c -> b4d8','read b550 -> b4dc'],
            shared_acc_scope='Caller composition uses an explicit callback; isolated body and0x902 verified separately in shared_timing_ring. Target ABI/address bridge and physical timer units not validated.',
            callback_may_change_shared_state=True,ready_vco_reads=False,
            b4e0_written_in_slice=False,deployed=False,
            sample_accesses=original_publish((1,1,0xa55a,3,0)),
            limitation='Original caller slice with intercepted0xacc; does not execute later calls at6202/620a or prove hardware readiness, atomicity, runtime flag producers or helper time bounds.'),
        shared_timing_ring=dict(entry='0xad0',stop='0xb52',helper='0x902 executed',cases=len(timing_cases),
            state='0x92ce halfword, modulo5',rings=['0x928c first snapshot','0x92a0 second snapshot'],
            system_reads=['0x500901f0','0x50090104','0x500900b8','0x500900bc','0x500900c0'],
            timer_poll='bit20, at most10 reads; original proceeds even if still set',
            modeled_extensions=['EXTHZ','BCLR','PULPv2 SWRR','HWLP_SETUP (ae8 only)'],
            hardware_loop_model='RI5CY manual rev4 page38: start=pc+4,end=pc+(uimm<<1),count=rs1. Hereaec..af8,count10; branch may exit early.',
            does_not_read_PLL=True,does_not_write_RF_configuration=True,deployed=False,
            limitation='Synthetic system-MMIO responses; no physical timer unit, simultaneous snapshot guarantee, actual bus latency or inter-core address bridge established. ABI prologue/epilogue excluded.'),
        request_B_chain=dict(entry='0x602c',stop='0x5360',cases=len(request_cases),
            C_entry='rf_core_rxon_request_b',original_helpers_executed=['0x37f0','0x4ec8','0x453c','0x3a7c'],
            stateful_bus=True,bus_widths=[2,4],modes=list(range(6)),selectors=[2,4,5,6,17],
            requested_raw_cases=[6812500,6875000,9992999,9993000,10000000],
            correction='Mode0 re-reads ZFIF index and signed table7b70 before coefficient production.',
            coefficient_order='Publish Q8, read MDLL state/lookup, publish and re-read factor, publish low then high.',
            normalization='Private immutable division byte lookups and mode image-table loads omitted; each omitted guest read checked against original image. Runtime context including b550/b538 retained.',
            deployed=False,hardware_tested=False,
            limitation='Initialized synthetic tables/context/MMIO only; no cold-start, caller post-processing, address bridge, RFAD freshness or PLL/analog proof.'),
        integrated_B_helpers=dict(entry='0x4ecc',stop='0x5360',cases=len(integrated_cases),
            original_helpers_executed=['0x453c','0x3a7c'],C_entry='rf_core_rxon_b_with_helpers',
            callbacks_replaced_by_actual_C=True,all_bus_widths=2,stateful_bus_fixture=True,
            normalization='Native private immutable mode-table loads omitted from bus trace because C embeds these verified constants. Runtime table/context/MMIO reads and all writes retained; mode writes compared to original image.',
            modes=[0,1,2,3,4,5],mode6_supported=False,precomputed_coefficients_required=True,
            deployed=False,hardware_tested=False,
            limitation='Synthetic initial RAM/MMIO, initialized only before execution. No ABI/caller/cold-start/address bridge, autonomous calibration, RF lock or received-signal proof.'),
        auxiliary_decode=dict(entry='0x602c',stop='0x609e',cases=len(auxiliary_cases),
            slot_source='RF auxiliary halfword bits15:12 at30054',context16_source='auxiliary bits11:0',
            correction_index_source='RXON word bits14:13 at6080; two bits, distinct from6390 retune one-bit field',
            bug_reproduction=dict(word='0x4221',old_C_index=0,native_index=2),
            scope='Pure context decode before correction selection; mode0 can subsequently replace index fromZFIF, so this is not full correction-path validation. Synthetic slot15 decode is not legal table-index authorization.'),
        parameter_decode=dict(entry='0x602c',stop='0x6080',cases=len(decode_cases),
            port_field='bits7:4 (4 bits), stored context+4; synthetic8..15 are decoding tests only, not authorized table indices',
            corrected_prior_C_mask='7 ->15; previous C lost input bit7; reproduced with word0x0080',
            selector_field='bits12:8',mode_field='bits3:0',modeled_extensions=['EXTHZ','EXTRACTU']),
        retained_board_route_chain=route_chain,
        native_b_coefficient_commit=dict(entry='0x4f98',stop='0x4fc4',
            source='Precomputed RF RAM b520 Q8 / b524 low / b522 high, no frequency calculation in this slice',
            accesses=[dict(operation='write16' if op else 'read16',address=hex(a),value=hex(v))
                      for op,a,v in commit_expected]),
        b4e0_producer=dict(reset_entry='0x10c2',reset_store='0x10d6',stop='0x10da',
            base='0xb468',offset='0x78',value=0,cases=reset_cases,
            all_runtime_writers_identified=False,field_name_confirmed=False,
            limitation='Positive reset-producer evidence only; does not prove no later writer or a permanent zero.'),
        native_b_mode_middle=dict(entry='0x50da',stop='0x529c',cases=len(middle_cases),
            original_instruction_boundaries_exercised=len(visited_middle),
            modeled_extensions=['EXTHZ','BSET','BNEM1','BEQM1'],
            saved_register_source={'0x30400':'LHU at4ed6 before prefix','0x30404':'LHU at4ee2 before prefix'},
            mode6_is_new_bandwidth=False,
            limitation='Modes7/65535 are synthetic branch tests, not supported receive or bandwidth modes.',
            sample_accesses=[dict(operation='write16' if op else 'read16',address=hex(a),value=hex(v))
                for op,a,v in original_middle(3,5,1,0,0xa55a,0x5aa5)]),
        native_b_completion=dict(entry='0x529c',stop='0x5354',cases=tail_cases,
            modeled_extensions=['EXTHZ','BCLR','BSET'],
            calibration_call={'site':'0x5354','target':'0x453c','argument':'rxon_context'},
            mode_call={'site':'0x535c','target':'0x3a7c','argument_source':'LHU context[0] at5358'},
            mode_argument_forwarding_cases=forwarded_modes,
            cal_status_reads_in_this_slice=False,
            limitation='No cal-status reads within this tail; not proof none exist in earlier stages or callees.'),
        sample_accesses=[dict(operation='write16' if op else 'read16',address=hex(a),value=hex(v))
                         for op,a,v in original(3,9,0xa55a)],
        shared_table_application=dict(entry='0x453c',cases=len(tables_cases),writes=9,register_feedback_reads=False,context_fields=['mode+0','selector+8','slot+0x14','control+0x16'],scope='Table/context application with repeated reads; no ready poll, no autonomous calibration or lock proof; caller guarantees valid indices.'),
        dependencies={p.relative_to(ROOT).as_posix():sha(p) for p in dependencies})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status='passed',builds=builds,output=str(args.output))))


if __name__=='__main__':
    main()
