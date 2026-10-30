"""Execute byte-matched vendor UDC queue/completion code offline.

OS critical sections, division and the application callback are stubs. The
controller is RAM: no USB IRQ timing, throughput or physical DMA is modeled.
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'work/host-test-deps'))
sys.path.insert(0, str(ROOT/'tools/usb'))
from inspect_udc import pac_ap
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pac', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    sdk = ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/CSDK_RDA8910.elf'
    names = ('prvEpQueueLocked', 'prvScheduleEpLocked.part.15', 'prvGiveBackEpCurrent',
             'prvGiveBackComplete_', 'prvEpXferStartLocked.isra.14')
    image = pac_ap(args.pac)
    load = struct.unpack_from('>I', image, 16)[0]
    payload = image[64:]
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    cpu.mem_map(0x60000000, 0x200000)
    cpu.mem_map(0x20000000, 0x20000)
    matched = []
    with sdk.open('rb') as stream:
        elf = ELFFile(stream)
        symbols = {s.name: s for s in elf.get_section_by_name('.symtab').iter_symbols()}
        # Map only .text; every nonselected external call must hit an explicit stub.
        text = elf.get_section_by_name('.text')
        cpu.mem_write(text['sh_addr'], text.data())
        for name in names:
            sym = symbols[name]
            address = sym['st_value'] & ~1
            section = elf.get_section(sym['st_shndx'])
            code = section.data()[address-section['sh_addr']:address-section['sh_addr']+sym['st_size']]
            assert len(code) == sym['st_size'] and code == payload[address-load:address-load+len(code)], name
            matched.append(dict(name=name, address=hex(address), bytes=len(code), sha256=hashlib.sha256(code).hexdigest()))
        entries = {name: symbols[name]['st_value'] for name in names}
    base, ep, fifo, regs, callback = 0x20000000, 0x20001000, 0x20001800, 0x20010000, 0x2001f000
    events = []
    callback_enqueues = [False]
    def get(a): return struct.unpack('<I', cpu.mem_read(a, 4))[0]
    def put(a, v): cpu.mem_write(a, struct.pack('<I', v & 0xffffffff))
    def ret(v=None):
        if v is not None: cpu.reg_write(UC_ARM_REG_R0, v)
        cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))
    # These addresses are SDK symbols/veneers, not hardware entry points.
    critical = (0x60153608, 0x60153724, 0x60153528)
    def execute(uc, address, size, context):
        if address in critical:
            ret(0 if address == critical[0] else None)
        elif address == 0x6001e5f8:
            ret(cpu.reg_read(UC_ARM_REG_R0)//cpu.reg_read(UC_ARM_REG_R1))
        elif address == 0x60153588:
            events.append(dict(event='vendor_trace'));ret()
        elif address in (0x600d3b6e, 0x600d3b8a):
            raise AssertionError('unexpected cache operation with uncached request')
        elif address == callback:
            req = cpu.reg_read(UC_ARM_REG_R1)
            assert not cpu.mem_read(req+40, 1)[0] & 2
            assert cpu.reg_read(UC_ARM_REG_R0) == ep
            events.append(dict(event='callback', request=hex(req), active=get(ep+20)))
            assert not callback_enqueues[0]  # callback only records; no AP worker pump
            ret()
    def write(uc, access, address, size, value, context):
        if regs <= address < regs+32:
            events.append(dict(event='controller_write', address=hex(address), bytes=size, value=hex(value)))
    cpu.hook_add(UC_HOOK_CODE, execute)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write)
    def call(name, *args_):
        cpu.reg_write(UC_ARM_REG_SP, 0x2001e000)
        cpu.reg_write(UC_ARM_REG_LR, 0x2001ff01)
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args_):
            cpu.reg_write(reg, value)
        cpu.emu_start(entries[name] | 1, 0x2001ff00, count=20000)
        assert cpu.reg_read(UC_ARM_REG_PC) == 0x2001ff00, name
        return cpu.reg_read(UC_ARM_REG_R0)
    def reset():
        cpu.mem_write(base, bytes(0x19000))
        cpu.mem_write(ep, bytes([0x81, 0]) + struct.pack('<H', 512))
        put(ep+4, regs);cpu.mem_write(ep+8, bytes([2]));put(ep+12, 8192)
        put(ep+16, fifo);put(ep+28, ep+24)
        events.clear()
    def request(index):
        req = base+0x2000+index*64
        cpu.mem_write(req, bytes(48))
        put(req, 0x80010000+index*8192);put(req+4, 8192)
        cpu.mem_write(req+17, bytes([1]));put(req+24, callback|1)
        return req
    reset()
    a,b,c = [request(i) for i in range(3)]
    for req in (a,b,c):assert call('prvEpQueueLocked', base, ep, req) == 0
    assert get(ep+20) == a and get(ep+24) == b and get(b+32) == c
    assert get(regs+20) == get(a)
    for current, following in ((a,b),(b,c),(c,0)):
        assert get(ep+20) == current
        put(current+8,8192);put(current+12,0)
        begin=len(events)
        call('prvGiveBackEpCurrent',base,ep)
        observed=events[begin:]
        assert observed[0]['event']=='callback' and observed[0]['active']==0
        assert get(ep+20)==following
        assert bool([row for row in observed if row['event']=='controller_write']) == bool(following)
        if following:assert get(regs+20)==get(following)
    assert get(ep+24)==0 and get(ep+28)==ep+24
    normal=list(events)
    # The explicit no-reschedule path used by cancellation must not start queued DMA.
    reset();a,b=[request(i) for i in range(2)]
    for req in (a,b):assert call('prvEpQueueLocked',base,ep,req)==0
    put(ep+20,0);events.clear()
    call('prvGiveBackComplete_',base,ep,a,0)
    assert get(ep+20)==0 and get(ep+24)==b
    assert not [row for row in events if row['event']=='controller_write']
    result=dict(status='passed',device_accessed=False,hardware_tested=False,
                pac=str(args.pac),vendor_function_bytes_match_pac=matched,
                three_requests_complete_without_worker_pump=True,
                callbacks_precede_next_controller_programming=True,
                explicit_no_reschedule_does_not_start_next=True,
                uncached_requests_skip_vendor_cache_operations=True,normal_events=normal,
                scope='Real vendor queue/schedule/giveback/DMA-program code with fake controller RAM. No IRQ timing, transfer-completion detection, USB throughput or cross-core supply proof.',
                dependencies={p.resolve().relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (Path(__file__), sdk, args.pac, ROOT/'tools/usb/inspect_udc.py')})
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('normal_events','dependencies','vendor_function_bytes_match_pac')},indent=2))


if __name__=='__main__':main()
