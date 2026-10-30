"""Build the v0.1 AP/CP service and a PAC from relocatable, pinned inputs.

Uses only source files, build-support archives and the v0.1 vendor platform
container. No project-state, seed PAC, SDK ELF, old work directory or historical
hardware report is required. Output is unflashed and never replaces a release.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import zlib

from elftools.elf.elffile import ELFFile
from prepare_build import prepare

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools/usb'))
from pac import entries, replace


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2)+'\n', encoding='utf-8')


def symbols(path):
    with path.open('rb') as stream:
        return {s.name:s['st_value'] for s in ELFFile(stream).get_section_by_name('.symtab').iter_symbols()}


def app_image(path):
    """SDK APP2 image format. CRC covers the image container, never raw IQ."""
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        syms = {s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        start,end = syms['__flash_start'],syms['__flash_end']
        if not 0 < end-start <= 0x180000:
            raise ValueError('APPIMG flash reservation exceeded')
        image = bytearray(end-start)
        for segment in elf.iter_segments():
            if segment['p_type'] != 'PT_LOAD':
                continue
            at = int(segment['p_paddr'])
            data = segment.data()
            lo,hi = max(start,at),min(end,at+len(data))
            if lo < hi:
                image[lo-start:hi-start] = data[lo-at:hi-at]
    if struct.unpack_from('<I',image)[0] != 0x41505032:
        raise ValueError('invalid APP2 magic')
    struct.pack_into('<II',image,4,len(image),0)
    struct.pack_into('<I',image,8,zlib.crc32(image)&0xffffffff)
    return bytes(image)


def check_uimage(data):
    header = bytearray(data[:64])
    magic,crc,_,length = struct.unpack_from('>4I',header)
    struct.pack_into('>I',header,4,0)
    if (magic != 0x27051956 or length != len(data)-64 or zlib.crc32(header)&0xffffffff != crc
            or zlib.crc32(data[64:])&0xffffffff != struct.unpack_from('>I',data,24)[0]):
        raise ValueError('invalid vendor AP uImage')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'work/build-v0.1',
                        help='new directory inside work/; never overwrites a release or previous build')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if os.name != 'nt':
        parser.error('this verified firmware recipe requires Windows and Python 3.10+')
    if not output.is_relative_to(ROOT/'work') or output == ROOT/'work' or output.exists():
        parser.error('choose a new directory strictly inside work/')
    config_path = ROOT/'firmware/platform/air724ug.json'
    cfg = json.loads(config_path.read_text(encoding='utf-8'))
    if (ROOT/'VERSION').read_text(encoding='utf-8').strip() != cfg['version']:
        raise ValueError('VERSION differs from firmware platform release version')
    base_path = ROOT/cfg['base_pac']
    base = base_path.read_bytes()
    if sha(base) != cfg['base_sha256']:
        raise ValueError('v0.1 platform PAC identity differs')
    before = entries(base)
    system = bytearray(before[cfg['system_entry']]['data'])
    check_uimage(system)
    # These addresses are fixed to the pinned vendor core, not guessed from a
    # possibly unrelated SDK. Check every bound function against that container.
    load = struct.unpack_from('>I',system,16)[0]
    macros = {'copsAddFunction':'COPS_ADD_FUNCTION','copsAssignInterface':'COPS_ASSIGN_INTERFACE',
              'copsGetCtrl':'COPS_GET_CTRL','drvUsbDisable':'DRV_USB_DISABLE',
              'drvUsbEnable':'DRV_USB_ENABLE','prvDwcEpQueue':'PRV_DWC_EP_QUEUE'}
    for name,fn in cfg['udc_functions'].items():
        at = (int(fn['address'],0)&~1)-load+64
        expected = bytes.fromhex(fn['prefix'])
        if at < 64 or system[at:at+len(expected)] != expected:
            raise ValueError('vendor UDC binding differs: '+name)
    deps = prepare()
    compiler = deps['arm-gcc']/'bin'
    gcc = compiler/'arm-none-eabi-gcc.exe'
    objcopy = compiler/'arm-none-eabi-objcopy.exe'
    ar = compiler/'arm-none-eabi-ar.exe'
    sdk = deps['sdk']
    output.mkdir(parents=True)
    generated = output/'generated'
    generated.mkdir()
    log = output/'build.log'
    commands = []

    def run(command):
        command = list(map(str,command))
        commands.append(command)
        with log.open('a',encoding='utf-8') as stream:
            stream.write(subprocess.list2cmdline(command)+'\n')
            stream.flush()
            result = subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        if result.returncode:
            print(log.read_text(encoding='utf-8',errors='replace')[-6000:],file=sys.stderr)
            raise subprocess.CalledProcessError(result.returncode,command)

    print('Building CP agent and matched resident/control...',flush=True)
    run([gcc,'-mcpu=cortex-a5','-mthumb','-mfloat-abi=soft','-Os','-ffreestanding',
         '-fno-builtin','-fno-stack-protector','-nostdlib','-Wl,--build-id=none',
         '-Wl,-T,'+str(ROOT/'firmware/debug_monitor/cp_agent.ld'),
         ROOT/'firmware/debug_monitor/cp_agent.c','-o',output/'cp_agent.elf'])
    run([objcopy,'-O','binary',output/'cp_agent.elf',output/'cp_agent.bin'])
    agent = (output/'cp_agent.bin').read_bytes()
    if sha(agent) != cfg['cp_agent_sha256']:
        raise ValueError('CP agent changed; review AP/CP binding before updating platform configuration')
    cp_dir = output/'cp'
    run([sys.executable,'-B',ROOT/'tools/build_capture_bridge.py','--platform',config_path,
         '--agent',output/'cp_agent.bin','--compiler-bin',compiler,'--output-dir',cp_dir,
         '--multi-profile','--max-bandwidth-index','5','--until-stop','--slot-bytes','8192',
         '--lossy-scratch','--rf-status-trace','--rf-status-dual-bank','--rf-status-fem',
         '--rf-status-fem-execution','--experimental-fem-override','--unrestricted-frequency',
         '--generation',cfg['generation']])
    cp = json.loads((cp_dir/'build.json').read_text(encoding='utf-8'))
    package = json.loads((cp_dir/'control.json').read_text(encoding='utf-8'))
    def blob(name,data):
        return ('static const unsigned char '+name+'[] __attribute__((aligned(32)))={'+
                ','.join(hex(x) for x in data)+'};\n')
    (generated/'cp_agent_blob.h').write_text(blob('cp_agent_blob',agent),encoding='utf-8')
    content = '#define SDR_BW0_CONTROL_ENTRY_OFFSET '+str(package['entry_offset'])+'u\n'
    content += '#define SDR_BW0_GENERATION '+cfg['generation']+'u\n'
    for name in ('resident','control'):
        content += blob('sdr_bw0_'+name+'_blob',(cp_dir/(name+'.bin')).read_bytes())
    (generated/'bw0_service_blob.h').write_text(content,encoding='utf-8')
    (generated/'rf_profiles_info.h').write_text(
        '#define SDR_RF_PROFILES_JSON '+json.dumps(json.dumps(cp['rf_profiles'],separators=(',',':')))+'\n'+
        '#define SDR_BW_INDICES_JSON "[0,1,2,3,4,5]"\n',encoding='utf-8')
    (generated/'cp_transport_binding.h').write_text(
        '#define CP_USB_MAILBOX '+cp['ap_mailbox']+'u\n#define CP_USB_GENERATION '+cfg['generation']+'u\n'+
        '#define CP_USB_PROGRESS 0x8096fec0u\n#define CP_USB_EXPORT 0x8096fa40u\n',encoding='utf-8')
    content = '#define SDR_USB_GLOBAL '+cfg['usb_global']+'u\n'
    for name,macro in macros.items():
        content += '#define SDR_ADDR_'+macro+' '+cfg['udc_functions'][name]['address']+'u\n'
    content += '#define SDR_QUEUE_PREFIX {'+','.join(hex(x) for x in
               bytes.fromhex(cfg['udc_functions']['prvDwcEpQueue']['prefix']))+'}\n'
    (generated/'udc_bindings.h').write_text(content,encoding='utf-8')
    includes = [sdk/p for p in ['core/iot_SDK_720U/memd','components/include','components/openat_inc',
                 'components/newlib/include','api/include','components/ril/inc']]
    includes += [ROOT/'firmware/debug_monitor',ROOT/'firmware/sdr_receiver',ROOT/'firmware/capture',generated]
    include_flags = ['-I'+str(p) for p in includes]
    defs = ['-DCSDK_PRO="sdr_receiver"','-DCSDK_VER="1.0.0"','-D_WINSOCKAPI_']
    feature_flags = ['-Wno-error=implicit-function-declaration','-Wno-error=incompatible-pointer-types',
        '-DRXCAPT_UNRESTRICTED_FREQUENCY=1','-DSDR_EXPERIMENTAL_FEM_OVERRIDE=1',
        '-DSDR_BW0_LOSSY_SCRATCH=1','-DSDR_RX_OUTPUT_SLOTS=6u','-DRXCAPT_FINITE_DATA_BYTES=8192u',
        '-DRXCAPT_FINITE_CAPTURE_END_ADDRESS=2047u','-std=gnu11']
    arch = ['-mcpu=cortex-a5','-mtune=generic-armv7-a','-mthumb','-mfpu=neon-vfpv4',
            '-mfloat-abi=hard','-mno-unaligned-access']
    common = feature_flags+arch+['-g','-Os','-Wall','-fno-strict-aliasing','-ffunction-sections','-fdata-sections']
    app_defs = ['-D'+x+'=1' for x in ['CP_USB_COMBINED_EXCHANGE','DBG_ENABLE_ASYNC_CALL',
                'DBG_ENABLE_BULK','DBG_ENABLE_BW0_USB','DBG_ENABLE_RAW_USB','SDR_BW0_CONTINUOUS',
                'SDR_USB_SEGMENT_PROFILE']]+['-DSDR_BW0_MAX_BW=5']
    obj_dir = output/'objects'
    obj_dir.mkdir()

    def compile_sources(sources,prefix,source_root,extra):
        objects=[]
        for index,name in enumerate(sources):
            obj = obj_dir/(prefix+'-'+str(index)+'.o')
            run([gcc,*defs,*extra,*include_flags,*common,'-o',obj,'-c',source_root/name])
            objects.append(obj)
        return objects

    print('Compiling SDK support and AP service...',flush=True)
    libraries=[]
    for name in ('api','ril'):
        objs = compile_sources(cfg[name+'_sources'],name,sdk,[])
        library = output/('lib'+name+'.a')
        run([ar,'qc',library,*objs])
        run([compiler/'arm-none-eabi-ranlib.exe',library])
        libraries.append(library)
    objects = compile_sources(cfg['ap_sources'],'ap',ROOT,
                              app_defs+['-Wextra','-Wno-misleading-indentation'])
    ldscript = output/'app.ld'
    run([gcc,*include_flags,'-E','-P','-x','c',sdk/'ldscripts/app_flashimg.ld','-o',ldscript])
    libgcc = deps['arm-gcc']/'lib/gcc/arm-none-eabi/7.2.1/thumb/v7-ar/fpv3/hard/libgcc.a'
    libc,libm = (sdk/'components/newlib/armca5'/n for n in ['libc.a','libm.a'])
    elf = output/'ap.elf'
    run([gcc,*feature_flags,*arch,'-Os','-T'+str(ldscript),'-Wl,--undefined=debug_at_write_filter',
         '-Wl,--undefined=debug_data_abort_gate',sdk/'core/iot_SDK_720U/lib/core_stub.o',*objects,
         '-o',elf,'-Wl,-Map='+str(output/'ap.map'),'-nostdlib','-Wl,--gc-sections',
         libraries[0],libc,libm,libgcc,libraries[1],libc,libm,libgcc])
    syms = symbols(elf)
    if (syms['test_ram'] != int(cp['ap_mailbox'],0) or syms['debug_data_abort_gate']&3
            or not syms['debug_at_write_filter']&1
            or not 0x60180000 <= syms['debug_at_write_filter'] < 0x60300000
            or syms['__ram_start'] != 0x80f00000 or syms['__ram_end'] > 0x81000000):
        raise ValueError('linked AP mailbox/hooks differ; do not package mismatched CP')
    image = app_image(elf)
    (output/'ap.img').write_bytes(image)
    if system[0x13164:0x13168] != bytes.fromhex('dff800f0') or system[0x1316c:0x1316e] != bytes.fromhex('00bf'):
        raise ValueError('vendor AP hook instruction differs')
    struct.pack_into('<I',system,0x13168,syms['debug_at_write_filter'])
    struct.pack_into('<I',system,0x3e0,syms['debug_data_abort_gate'])
    struct.pack_into('>I',system,24,zlib.crc32(system[64:])&0xffffffff)
    struct.pack_into('>I',system,4,0)
    struct.pack_into('>I',system,4,zlib.crc32(system[:64])&0xffffffff)
    check_uimage(system)
    candidate = replace(base,{cfg['system_entry']:bytes(system),cfg['app_entry']:image})
    after = entries(candidate)
    changed = [n for n in after if after[n]['data'] != before[n]['data']]
    if set(changed)-{cfg['system_entry'],cfg['app_entry']}:
        raise ValueError('unexpected vendor CP/RF/NV/boot changes')
    pac = output/'Air724UG_SDR_v0.1.pac'
    pac.write_bytes(candidate)
    source_files = [p for p in (ROOT/'firmware').rglob('*') if p.is_file()]
    source_files += [Path(__file__),ROOT/'tools/build_capture_bridge.py',ROOT/'tools/prepare_build.py',
                     ROOT/'tools/usb/pac.py',ROOT/'tools/debug/uis_debug.py',
                     ROOT/'tools/sdr/rf_catalog.py',ROOT/'build-support/manifest.json',ROOT/'VERSION']
    report = dict(status='built_not_flashed',release_version=cfg['version'],device_accessed=False,
        hardware_tested=False,flashed=False,firmware_identity=cfg['identity'],generation=cfg['generation'],
        pac=pac.relative_to(ROOT).as_posix(),sha256=sha(candidate),bytes=len(candidate),
        base_pac=cfg['base_pac'],base_sha256=sha(base),byte_identical_to_release=candidate==base,
        changed_entries=changed,unchanged_cp_rf_nv_boot=True,ap_test_ram=hex(syms['test_ram']),
        app_ram_end=hex(syms['__ram_end']),elf=elf.relative_to(ROOT).as_posix(),elf_sha256=sha(elf.read_bytes()),
        appimg_sha256=sha(image),cp_modules=(cp_dir/'build.json').relative_to(ROOT).as_posix(),
        resident_bytes=cp['resident']['bytes'],control_bytes=cp['control']['bytes'],
        source_sha256={p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in sorted(set(source_files))},
        log=log.relative_to(ROOT).as_posix())
    save(output/'build.json',report)
    save(output/'commands.json',commands)
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},indent=2))


if __name__ == '__main__':
    main()
