"""Conservative direct AUIPC/ADDI address references in original RF image."""
import hashlib,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/host-test-deps'))
from capstone import Cs,CS_ARCH_RISCV,CS_MODE_RISCV32,CS_MODE_RISCVC

def number(value):return int(value,0)

def constant_accesses(raw, limit=0x7bc0, target=0xb4e0, target_bytes=2):
    """Bounded basic-block constant propagation over native instruction widths.

    Track only LUI/AUIPC/ADDI and selected compressed pointer moves/adds.
    Unknown instructions discard constants; branches/calls end the block.
    This intentionally cannot establish absence of indirect writes.
    """
    constants={0:0}; accesses=[]; pc=0; unknown=0
    def signed(v,b):return v-(1<<b) if v&(1<<(b-1)) else v
    def assign(reg,value):
        if reg:
            constants.pop(reg,None)
            if value is not None:constants[reg]=value&0xffffffff
    def memory(kind,base,offset,width,source=None):
        if base not in constants:return
        address=(constants[base]+offset)&0xffffffff
        if address<target+target_bytes and address+width>target:
            accesses.append(dict(pc=hex(pc),kind=kind,address=hex(address),width=width,
                                 value=constants.get(source) if source is not None else None))
    while pc<min(limit,len(raw)):
        half=int.from_bytes(raw[pc:pc+2],'little');width=4 if half&3==3 else 2
        word=int.from_bytes(raw[pc:pc+width],'little')
        if width==4:
            op=word&127;rd=(word>>7)&31;rs=(word>>15)&31;rs2=(word>>20)&31
            if op==0x17:assign(rd,pc+(word&0xfffff000))
            elif op==0x37:assign(rd,word&0xfffff000)
            elif op==0x13 and (word>>12)&7==0:
                assign(rd,constants[rs]+signed(word>>20,12) if rs in constants else None)
            elif op==0x03:
                size={0:1,1:2,2:4,4:1,5:2}.get((word>>12)&7)
                if size:memory('read',rs,signed(word>>20,12),size)
                assign(rd,None)
            elif op==0x23:
                size={0:1,1:2,2:4}.get((word>>12)&7)
                if size:memory('write',rs,signed(((word>>25)<<5)|((word>>7)&31),12),size,rs2)
            else:
                constants={0:0};unknown+=1
        else:
            quadrant=half&3;funct=half>>13;rd=(half>>7)&31
            imm=signed(((half>>12)&1)*32+((half>>2)&31),6)
            if quadrant==1 and funct==0:assign(rd,constants[rd]+imm if rd in constants else None)
            elif quadrant==1 and funct==2:assign(rd,imm)
            elif quadrant==1 and funct==3 and rd not in (0,2):assign(rd,imm<<12)
            elif quadrant==2 and funct==4 and rd and ((half>>2)&31):
                rs=(half>>2)&31
                value=constants.get(rs)
                if half&0x1000:value=constants[rd]+value if rd in constants and value is not None else None
                assign(rd,value)
            else:
                constants={0:0};unknown+=1
        constants[0]=0;pc+=width
    return dict(accesses=accesses,unknown_or_control_boundaries=unknown,
                scope='Instruction-width scan, conservative constant pointers within blocks only; unknown/PULP/control instructions reset facts. No indirect alias, interprocedural or write-absence proof.')

def main():
    # Pointer-copy/offset case absent from the former adjacent-pair scan.
    def addi(rd,rs,imm):return ((imm&4095)<<20)|(rs<<15)|(rd<<7)|0x13
    def store(rs,base,imm,f=1):
        return (((imm&4095)>>5)<<25)|(rs<<20)|(base<<15)|(f<<12)|((imm&31)<<7)|0x23
    def packed(words):return b''.join(w.to_bytes(4,'little') for w in words)
    prefix=[0xb000|(5<<7)|0x37,addi(5,5,0x400),addi(6,5,0),addi(6,6,0xe0)]
    probe=constant_accesses(packed(prefix+[store(0,6,0)]))
    assert probe['accesses']==[dict(pc='0x10',kind='write',address='0xb4e0',width=2,value=0)]
    # Unknown op and branch must invalidate the copied pointer, not leak facts.
    for barrier in (0xffffffff,0x00000463):
        assert not constant_accesses(packed(prefix+[barrier,store(0,6,0)]))['accesses']
    # Detect a wide store which overlaps the flag without beginning at it.
    overlap=constant_accesses(packed(prefix+[store(0,6,-2,2)]))['accesses']
    assert len(overlap)==1 and overlap[0]['address']=='0xb4de' and overlap[0]['width']==4
    assert not constant_accesses(packed(prefix+[store(0,6,0)]),target=0xb4ee)['accesses']
    image=ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin/riscV.bin'
    raw=image.read_bytes();decoder=Cs(CS_ARCH_RISCV,CS_MODE_RISCV32|CS_MODE_RISCVC);decoder.skipdata=True
    ins=list(decoder.disasm(raw[:0x7bc0],0));hits=[]
    for index,first in enumerate(ins[:-1]):
        if first.mnemonic!='auipc':continue
        match=re.fullmatch(r'(\w+),\s*(-?(?:0x[0-9a-f]+|\d+))',first.op_str)
        if not match:continue
        reg=match[1];base=(first.address+(number(match[2])<<12))&0xffffffff
        nxt=ins[index+1]
        if nxt.mnemonic!='addi':continue
        m=re.fullmatch(r'(\w+),\s*(\w+),\s*(-?(?:0x[0-9a-f]+|\d+))',nxt.op_str)
        if not m or m[1]!=reg or m[2]!=reg:continue
        base=(base+number(m[3]))&0xffffffff
        for op in ins[index+2:index+12]:
            m=re.fullmatch(r'(\w+),\s*(-?(?:0x[0-9a-f]+|\d+))\((\w+)\)',op.op_str)
            if m and m[3]==reg and ((base+number(m[2]))&0xffffffff)==0xb4e0:
                hits.append({'address':hex(op.address),'opcode':op.mnemonic,'operands':op.op_str,'base_producer':hex(first.address)})
            # Only trust straight-line prefix, stop when base can change.
            if op.mnemonic.startswith(('b','j','c.b','c.j')) or op.mnemonic=='.byte':break
            if op.mnemonic not in ('sh','sw','sb') and op.op_str.split(',')[0].strip()==reg:break
    assert any(h['address']=='0x10d6' and h['opcode']=='sh' for h in hits)
    assert any(h['address']=='0x5128' and h['opcode']=='lhu' for h in hits)
    propagated=constant_accesses(raw)
    assert any(h['pc']=='0x10d6' and h['kind']=='write' and h['value']==0 for h in propagated['accesses'])
    assert any(h['pc']=='0x5128' and h['kind']=='read' for h in propagated['accesses'])
    caller_references={hex(a):constant_accesses(raw,target=a) for a in
        (0xb4d2,0xb4d8,0xb4dc,0xb4ee,0xb4f2,0xb52c,0xb550)}
    # Positive producer evidence only. Missing indirect accesses remain unknown.
    for address,pc,value in [('0xb4ee','0x36f2',1),('0xb4ee','0x3778',0),
                             ('0xb4f2','0x3542',1),('0xb4f2','0x35d0',0),
                             ('0xb52c','0x61d8',1),('0xb52c','0x6902',0)]:
        assert any(h['pc']==pc and h['kind']=='write' and h['value']==value
                   for h in caller_references[address]['accesses'])
    paths=[Path(__file__).resolve(),image]
    report={'status':'passed','device_accessed':False,'hardware_tested':False,'direct_references':hits,
        'bounded_constant_pointer_references':propagated,
        'caller_state_references':caller_references,
        'scanner_tests':['pointer copy and offset','unknown/control boundary invalidation','overlapping wide store'],
        'scope':'Linear Capstone decoding of first 0x7bc0 bytes, only immediately adjacent AUIPC/ADDI base and next bounded straight-line accesses. Legacy PULP instructions and other pointer production are not modeled; missing matches do not prove absent reads or writes.',
        'dependencies':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    (ROOT/'records/rf/reference-rf-dual-v17-flag-direct-references.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'passed','direct_references':hits},indent=2))
if __name__=='__main__':main()
