"""Extract/decode current PAC RF and validate its SDK container consumer offline."""
import hashlib
import importlib.util
import json
import struct
import sys
import subprocess
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sdk_layout(payload, elf_path):
    """Compare a bounded parser with the SDK ARM wrapper; model only block decode."""
    sys.path.insert(0, str(ROOT/'work/host-test-deps'))
    from elftools.elf.elffile import ELFFile
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
    total, block_kib, dict_kib, reserved = struct.unpack_from('<IHBB', payload)
    assert total > 0 and block_kib > 0 and dict_kib > 0 and reserved == 0
    blocks = []; offset = 8; remaining = total
    while remaining:
        assert offset+8 <= len(payload)
        size, check = struct.unpack_from('<2I', payload, offset)
        end = offset+8+size; padded = offset+8+((size+7)&~7)
        assert size > 0 and end <= padded <= len(payload)
        assert not any(payload[end:padded])
        output = min(remaining, block_kib*1024)
        blocks.append(dict(header_offset=offset, stream_offset=offset+8,
                           compressed_bytes=size, output_bytes=output, hardware_result=check))
        offset = padded; remaining -= output
    assert offset == len(payload)
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    with elf_path.open('rb') as stream:
        elf = ELFFile(stream)
        symbols = {s.name: int(s['st_value']) for s in elf.get_section_by_name('.symtab').iter_symbols()}
        wrapper = symbols['halLzmaDecompressFile']; helper = symbols['halLzmaDecompressBlock']
        # Map only file-backed load segments; no peripheral is mapped or executed.
        mapped = set()
        for seg in elf.iter_segments():
            if seg['p_type'] != 'PT_LOAD' or not seg['p_filesz']: continue
            address = int(seg['p_vaddr']); data = seg.data()
            for page in range(address&~4095, (address+len(data)+4095)&~4095, 4096):
                if page not in mapped: cpu.mem_map(page,4096); mapped.add(page)
            cpu.mem_write(address,data)
    cpu.mem_map(0x80000000,0x30000); cpu.mem_map(0x10000000,0x10000)
    source=0x80000000; dest=0x80010000; stop=0x10000000; stack=0x1000f000
    cpu.mem_write(source,payload); calls=[]; mode='success'
    def hook(uc, address, size, context):
        if address == (helper&~1):
            i=len(calls); assert i < len(blocks)
            args=[uc.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
            sp=uc.reg_read(UC_ARM_REG_SP)
            dictionary,result_ptr=struct.unpack('<2I',uc.mem_read(sp,8))
            block=blocks[i]
            assert args == [source+block['stream_offset'],block['compressed_bytes'],dest+sum(b['output_bytes'] for b in blocks[:i]),block['output_bytes']]
            assert dictionary == dict_kib*1024
            calls.append(dict(arguments=args,dictionary_bytes=dictionary))
            uc.mem_write(result_ptr,struct.pack('<I',block['hardware_result'] ^ (1 if mode=='mismatch' else 0)))
            uc.reg_write(UC_ARM_REG_R0,0 if mode=='failure' else 1); uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
    cpu.hook_add(UC_HOOK_CODE,hook)
    cpu.reg_write(UC_ARM_REG_R0,source); cpu.reg_write(UC_ARM_REG_R1,dest)
    cpu.reg_write(UC_ARM_REG_SP,stack); cpu.reg_write(UC_ARM_REG_LR,stop|1)
    cpu.emu_start(wrapper,stop,count=10000)
    assert cpu.reg_read(UC_ARM_REG_PC)==stop and cpu.reg_read(UC_ARM_REG_R0)==total and len(calls)==len(blocks)
    valid_calls=list(calls)
    # The wrapper rejects unaligned pointers before entering the block decoder.
    rejected=[]
    for input_addr,output_addr in ((source+1,dest),(source,dest+2),(0,dest),(source,0)):
        calls.clear()
        cpu.reg_write(UC_ARM_REG_R0,input_addr); cpu.reg_write(UC_ARM_REG_R1,output_addr)
        cpu.reg_write(UC_ARM_REG_SP,stack); cpu.reg_write(UC_ARM_REG_LR,stop|1)
        cpu.emu_start(wrapper,stop,count=10000)
        assert cpu.reg_read(UC_ARM_REG_PC)==stop and cpu.reg_read(UC_ARM_REG_R0)==0xffffffff and not calls
        rejected.append([input_addr,output_addr])
    for mode in ('mismatch','failure'):
        calls.clear()
        cpu.reg_write(UC_ARM_REG_R0,source); cpu.reg_write(UC_ARM_REG_R1,dest)
        cpu.reg_write(UC_ARM_REG_SP,stack); cpu.reg_write(UC_ARM_REG_LR,stop|1)
        cpu.emu_start(wrapper,stop,count=10000)
        assert cpu.reg_read(UC_ARM_REG_PC)==stop and cpu.reg_read(UC_ARM_REG_R0)==0xffffffff and len(calls)==1
    return dict(total_output_bytes=total,block_bytes=block_kib*1024,dictionary_bytes=dict_kib*1024,
                blocks=blocks,native_wrapper=hex(wrapper),native_block_helper=hex(helper),native_calls=valid_calls,
                rejected_pointer_cases=rejected,
                rejected_decoder_cases=['hardware result mismatch','block helper failure'],
                scope='Original SDK ARM wrapper with synthetic successful block decoder/check result; no decompression or hardware execution.')


def main():
    spec = importlib.util.spec_from_file_location('service_pac', ROOT/'tools/usb/pac.py')
    pac = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pac)
    manifest = ROOT/'outputs/firmware/current/manifest.json'
    installed = json.loads(manifest.read_text())['installed_firmware']
    path = ROOT/installed['pac']
    blob = path.read_bytes()
    assert hashlib.sha256(blob).hexdigest() == installed['sha256']
    entries = pac.entries(blob)
    names = [n for n in entries if 'BB_RF_SS_NoVolte_cus.img' in n]
    assert len(names) == 1
    modem = entries[names[0]]['data']
    headers = [o for o in range(0, len(modem)-512, 512)
               if modem[o:o+8] == b'\xe5\x01\0\0FILE' and
               modem[o+8:o+72].split(b'\0')[0] == b'riscV.bin.000']
    assert len(headers) == 1
    offset = headers[0]
    size = struct.unpack_from('<I', modem, offset+72)[0]
    count = (size+499)//500
    assert 0 < size <= 65536 and 100+2*count <= 512
    pages = struct.unpack_from('<'+str(count)+'H', modem, offset+100)
    assert len(set(pages)) == len(pages)
    chunks = []
    for page in pages:
        at = page*512
        assert at+512 <= len(modem) and modem[at:at+4] == b'\xe5\x01\0\0'
        flags,stored_page=struct.unpack_from('<2H',modem,at+504)
        assert flags==1 and stored_page==page
        assert zlib.crc32(modem[at:at+508])==struct.unpack_from('<I',modem,at+508)[0]
        chunks.append(modem[at+4:at+504])
    payload = b''.join(chunks)[:size]
    sdk = ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin/riscV.bin'
    assert struct.unpack_from('<I', payload)[0] == sdk.stat().st_size
    layout=ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/CSDK_RDA8910.elf'
    parsed=sdk_layout(payload,layout)
    out = ROOT/'work/rf-cache/current-rf-compressed.bin'
    out.write_bytes(payload)
    codec=ROOT/'inputs/repositories/rda8910-csdk-hotelec/tools/win32/lzmar.exe'
    with tempfile.TemporaryDirectory(dir=ROOT/'work') as temporary:
        folder=Path(temporary); decoded=folder/'decoded.bin'; encoded=folder/'encoded.bin'; roundtrip=folder/'roundtrip.bin'
        def run(*args):
            result=subprocess.run([str(codec),*map(str,args)],capture_output=True,timeout=10)
            assert result.returncode==0,repr(result.stdout+result.stderr)
        run('d2',out,decoded)
        actual=decoded.read_bytes(); expected=sdk.read_bytes()
        assert len(actual)==parsed['total_output_bytes']
        run('e2',65536,sdk,encoded); run('d2',encoded,roundtrip)
        assert roundtrip.read_bytes()==expected
    (ROOT/'work/rf-cache/current-rf-decoded.bin').write_bytes(actual)
    differences=[i for i,(a,b) in enumerate(zip(actual,expected)) if a!=b]
    runs=[]
    for i in differences:
        if runs and runs[-1][1]==i:runs[-1][1]=i+1
        else:runs.append([i,i+1])
    report = dict(status='passed', device_accessed=False, pac=installed['pac'],
        pac_sha256=installed['sha256'], modem_entry=names[0], header_offset=hex(offset),
        file_name='riscV.bin.000', bytes=size, pages=list(pages),
        page_data_bytes=500,page_footer_bytes=8,page_crc32_verified=True,
        supersedes_incorrect_508byte_extraction=True,
        payload_sha256=hashlib.sha256(payload).hexdigest(), header_hex=payload[:16].hex(),
        declared_uncompressed_bytes=struct.unpack_from('<I',payload)[0],
        sdk_block_layout=parsed,
        supersedes_reference_3u32_header=True,
        sdk_bytes=sdk.stat().st_size, sdk_sha256=hashlib.sha256(sdk.read_bytes()).hexdigest(),
        decompressed=True, content_identity_proved=actual==expected,
        decoded_sha256=hashlib.sha256(actual).hexdigest(),
        sdk_roundtrip_verified=True, different_bytes=len(differences),different_ranges=runs,
        scope='PAC extraction, original SDK ARM wrapper and vendor codec with SDK roundtrip; decoded PAC differs from reference SDK and is not a live RF RAM readback or repacking specification.',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in (Path(__file__),ROOT/'tools/usb/pac.py',manifest,layout,codec,sdk)})
    dest = ROOT/'records/rf/reference-rf-pac-payload.json'
    dest.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status='passed',bytes=size,declared_bytes=report['sdk_bytes'],decompressed=True,sdk_different_bytes=len(differences))))


if __name__ == '__main__':
    main()
