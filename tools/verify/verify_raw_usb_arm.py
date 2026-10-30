"""Execute compiled raw-USB descriptor/control handlers in ARM emulation.

UDC/OS calls are stubbed; this verifies ARM code and wire layouts, not USB DMA.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'work/host-test-deps'))
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC)

RETURN = 0x70000000
ENQUEUE = 0x70000100
FALLBACK = 0x70000200
COMPLETE_RETURN = 0x70000300
ALLOCATE = 0x70000400
FREE = 0x70000500
DEQUEUE = 0x70000600
UDC = 0x80d00000
CTRL = 0x80d10000
XFER = 0x80d11000
CONTROL_BUFFER = 0x80d12000
COMPOSITE = 0x80d20000
SETUP = 0x80d21000
INPUT = 0x80d22000
OUTPUT = 0x80d23000
OUTPUT_SIZE = 0x80d24000


class Machine:
    def __init__(self, elf_path, bindings):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.uc.mem_map(0x60000000, 0x400000)
        self.uc.mem_map(0x80000000, 0x1000000)
        self.uc.mem_map(RETURN, 0x1000)
        with elf_path.open('rb') as stream:
            elf = ELFFile(stream)
            self.symbols = {s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
            for segment in elf.iter_segments():
                if segment['p_type'] == 'PT_LOAD' and segment['p_filesz']:
                    self.uc.mem_write(segment['p_vaddr'], segment.data())
        self.uc.reg_write(UC_ARM_REG_C1_C0_2, 0xf00000)
        self.uc.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        self.reply = None
        self.fallbacks = 0
        self.worker_mode = False
        self.worker_finished = False
        self.clock = 0
        self.allocated = 0
        self.freed = 0
        self.enqueue_return = None
        self.bindings = bindings
        self.uc.hook_add(UC_HOOK_CODE, self.hook)
        self.put(UDC, 3)
        self.put(UDC+44, ENQUEUE|1)
        self.put(UDC+96, 0x80d30000)
        self.put(UDC+76, ALLOCATE|1, FREE|1)
        self.put(UDC+52, DEQUEUE|1)
        self.put(CTRL, XFER, CONTROL_BUFFER, 512)
        self.put(self.symbols['raw']+40, COMPOSITE, UDC)
        self.put(self.symbols['raw']+64, 0x80d30000, 5, 1, 1)
        self.uc.mem_write(0x80d30000, bytes.fromhex('86000002'))
        self.put(self.symbols['original_setup'], FALLBACK|1)
        self.put(self.symbols['stats'], 0x31525153, 1, 0)
        self.uc.mem_write(self.symbols['raw']+48, bytes([9,4,5,0,1,255,0x53,0x44,0,7,5,0x86,2,0,2,0]))

    def put(self, address, *values):
        self.uc.mem_write(address, struct.pack('<'+'I'*len(values), *values))

    def word(self, address):
        return struct.unpack('<I', self.uc.mem_read(address,4))[0]

    def hook(self, uc, address, size, _):
        value = None
        if address == RETURN:
            uc.emu_stop()
            return
        if address == (self.bindings['COPS_GET_CTRL']&~1):
            value = CTRL
        elif address == (self.symbols['osiEnterCritical']&~1):
            value = 1
        elif address in {(self.symbols[n]&~1) for n in ('osiExitCritical','osiSemaphoreRelease')}:
            value = 0
        elif address == ENQUEUE:
            xfer = uc.reg_read(UC_ARM_REG_R2)
            pointer, length, actual, status = struct.unpack('<4I',uc.mem_read(xfer,16))
            self.reply = bytes(uc.mem_read(pointer,length))
            assert uc.reg_read(UC_ARM_REG_R0) == UDC
            assert uc.reg_read(UC_ARM_REG_R1) == 0x80d30000
            assert actual == status == 0
            if self.worker_mode:
                assert uc.mem_read(xfer+17,1) == b'\1'
                self.put(xfer+8,length,0)
                self.enqueue_return=uc.reg_read(UC_ARM_REG_LR)
                uc.reg_write(UC_ARM_REG_R0,uc.reg_read(UC_ARM_REG_R1))
                uc.reg_write(UC_ARM_REG_R1,xfer)
                uc.reg_write(UC_ARM_REG_LR,COMPLETE_RETURN|1)
                uc.reg_write(UC_ARM_REG_PC,self.word(xfer+24))
                return
            assert uc.mem_read(xfer+17,1) == b'\0'  # control replies use CPU cache clean
            value = 0
        elif address == FALLBACK:
            self.fallbacks += 1
            value = 0xffffffff
        elif address == COMPLETE_RETURN:
            uc.reg_write(UC_ARM_REG_R0,0)
            uc.reg_write(UC_ARM_REG_PC,self.enqueue_return)
            return
        elif address == ALLOCATE:
            value=0x80d40000+self.allocated*64
            self.allocated+=1
            assert self.allocated<128
        elif address == FREE:
            self.freed+=1
            value=0
        elif address == DEQUEUE:
            value=0
        elif address == (self.symbols['osiUpTimeUS']&~1):
            self.clock+=100
            uc.reg_write(UC_ARM_REG_R1,0)
            value=self.clock
        elif address == (self.symbols['osiSemaphoreAcquire']&~1):
            if self.worker_mode and self.word(self.symbols['stats']+6*4) in (3,4):
                self.worker_finished=True
                uc.emu_stop()
                return
            value=0
        elif address == (self.symbols['osiSemaphoreTryAcquire']&~1):
            self.clock+=1000
            value=0
        if value is not None:
            uc.reg_write(UC_ARM_REG_R0,value)
            uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))

    def call(self, name, *args):
        self.uc.reg_write(UC_ARM_REG_SP,0x80ff0000)
        self.uc.reg_write(UC_ARM_REG_LR,RETURN)
        for register,value in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),args):
            self.uc.reg_write(register,value)
        if len(args)>4:
            self.put(0x80ff0000,*args[4:])
        self.uc.emu_start(self.symbols[name]|1, RETURN, timeout=10000000, count=1000000)
        if self.uc.reg_read(UC_ARM_REG_PC) != RETURN and not self.worker_finished:
            raise RuntimeError(f'ARM handler did not return: {name}, pc={self.uc.reg_read(UC_ARM_REG_PC):#x}, '
                f'clock={self.clock}, state={self.word(self.symbols["stats"]+24)}, '
                f'allocated={self.allocated}, freed={self.freed}')
        return self.uc.reg_read(UC_ARM_REG_R0)

    def setup(self, kind, request, value, index, length):
        self.reply = None
        self.uc.mem_write(SETUP,struct.pack('<BBHHH',kind,request,value,index,length))
        result = self.call('windows_setup',COMPOSITE,SETUP)
        return result,self.reply

    def control(self, operation, payload=b''):
        if payload:
            self.uc.mem_write(INPUT,payload)
        self.put(OUTPUT_SIZE,0xdeadbeef)
        result = self.call('sdr_raw_control',operation,INPUT,len(payload),OUTPUT,OUTPUT_SIZE)
        length = self.word(OUTPUT_SIZE)
        assert length<=128
        return result,bytes(self.uc.mem_read(OUTPUT,length))


def verify(elf_path, binding_path):
    import re
    bindings = {n:int(v,16) for n,v in re.findall(r'#define SDR_ADDR_(\w+) (0x[0-9a-f]+)u',binding_path.read_text())}
    m = Machine(elf_path,bindings)
    cases=[]
    code,reply=m.setup(0x80,6,0x03ee,0,255)
    assert code==0 and reply==bytes([18,3])+('MSFT100'.encode('utf-16le'))+b'\x5a\0'
    cases.append('OS string exact layout')
    assert m.setup(0x80,6,0x03ee,0,8)[1]==reply[:8]
    cases.append('OS string short read')
    code,reply=m.setup(0xc0,0x5a,0,4,255)
    assert code==0 and len(reply)==40 and struct.unpack_from('<IHHB',reply)==(40,0x100,4,1)
    assert reply[16:18]==b'\x05\x01' and reply[18:26]==b'WINUSB\0\0'
    cases.append('WINUSB compatible ID targets only added interface')
    assert m.setup(0xc0,0x5a,0,4,16)[1]==reply[:16]
    cases.append('compatible ID header query')
    code,reply=m.setup(0xc1,0x5a,5,5,65535)
    assert code==0 and len(reply)==142 and struct.unpack_from('<IHHH',reply)==(142,0x100,5,1)
    assert struct.unpack_from('<IIH',reply,10)==(132,1,40)
    assert reply[20:60].decode('utf-16le')=='DeviceInterfaceGUID\0'
    assert struct.unpack_from('<I',reply,60)[0]==78
    assert reply[64:].decode('utf-16le')=='{5D6BCE91-4F8A-4D42-9A0D-A9E6F8AC8910}\0'
    cases.append('extended properties lengths Unicode and GUID')
    assert m.setup(0xc1,0x5a,4,5,255)==(0xffffffff,None)
    cases.append('reject wrong interface properties query')
    assert m.setup(0x80,6,0x0100,0,18)==(0xffffffff,None) and m.fallbacks==1
    cases.append('unrelated control requests delegate to vendor handler')
    assert m.call('fill',m.symbols['raw'],OUTPUT,512)==16
    descriptor=bytes(m.uc.mem_read(OUTPUT,16))
    assert descriptor==bytes.fromhex('0904050001ff53440007058602000200')
    cases.append('High-Speed vendor Bulk descriptor')
    m.put(UDC,2)
    assert m.call('fill',m.symbols['raw'],OUTPUT,10)==10
    assert m.call('fill',m.symbols['raw'],OUTPUT,16)==16
    assert bytes(m.uc.mem_read(OUTPUT+13,2))==b'\x40\0'
    cases.append('Full-Speed packet size and bounded descriptor copy')
    assert m.control(41,struct.pack('<4I',1,1000,8192,8))[0]==10
    cases.append('benchmark refuses Full-Speed')
    m.put(UDC,3)
    for payload,status in [(b'',1),(struct.pack('<4I',2,1000,8192,8),1),
        (struct.pack('<4I',1,99,8192,8),2),(struct.pack('<4I',1,60001,8192,8),2),
        (struct.pack('<4I',1,1000,8000,8),2),(struct.pack('<4I',1,1000,65536,1),2),
        (struct.pack('<4I',1,1000,32768,9),2),(struct.pack('<4I',1,1000,512,0),2)]:
        assert m.control(41,payload)[0]==status
        cases.append('start rejects invalid payload '+payload.hex())
    assert m.control(41,struct.pack('<4I',1,1000,8192,8))==(0,b'\x01\0\0\0')
    cases.append('start accepts bounded aligned configuration')
    assert m.control(41,struct.pack('<4I',1,1000,8192,8))[0]==5
    cases.append('duplicate active start is BUSY')
    assert m.control(42)==(0,b'')
    assert m.word(m.symbols['stop_requested'])==1
    cases.append('stop requests worker drain')
    code,status=m.control(40)
    assert code==0 and len(status)==128 and struct.unpack_from('<3I',status)==(0x31525153,1,0)
    assert struct.unpack_from('<3I',status,12)==(5,0x86,1)
    cases.append('status metadata is separate fixed control reply')
    assert m.control(40,b'x')[0]==1 and m.control(99)[0]==4
    cases.append('invalid status and unknown operation bounded')
    # Exercise actual compiled worker/ring/adapter with synchronous fake UDC
    # completions. Timing is synthetic, so it cannot yield a USB speed result.
    m=Machine(elf_path,bindings)
    m.worker_mode=True
    for generation in (1,2):
        m.worker_finished=False
        assert m.control(41,struct.pack('<4I',1,100,8192,8))==(0,struct.pack('<I',generation))
        m.call('worker',0)
        assert m.worker_finished
        code,body=m.control(40)
        words=struct.unpack('<32I',body)
        assert code==0 and words[6]==3 and words[7]==0 and words[8]==generation
        assert words[14]>0 and words[15:18]==(0,0,0)
        assert words[18]+(words[19]<<32)==words[14]*8192
        assert m.allocated==m.freed==generation*8
    cases.append('compiled worker finite source drains and reopens for two epochs with fake synchronous UDC')
    return dict(status='passed',elf=str(elf_path.relative_to(ROOT)),elf_sha256=hashlib.sha256(elf_path.read_bytes()).hexdigest(),
        hardware_tested=False,device_accessed=False,tests=cases,
        scope='actual ARM descriptor/control code executed; OS/UDC calls stubbed; no USB timing DMA or enumeration proof')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir',type=Path,required=True,help='explicit AP build directory')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    build=args.build_dir.resolve()
    manifest=build/'build.json'
    if manifest.is_file():
        elf=ROOT/json.loads(manifest.read_text(encoding='utf-8'))['elf']
    else:
        elf=build/'csdk/hex/Air720U_V403028_CSDK_demo_sdr_receiver.elf'
    report=verify(elf,build/'generated/udc_bindings.h')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
