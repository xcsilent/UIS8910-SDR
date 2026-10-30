"""Build a raw-USB service candidate from retained sources and the installed PAC.

No device access or flashing. Preserves the installed CP/RF/NV/boot payloads.
Only the APPIMG and its two existing AP entry hooks are replaced.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zlib

from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT/'inputs/repositories/rda8910-csdk-hotelec'
sys.path.insert(0, str(ROOT/'tools/usb'))
from inspect_udc import inspect
from pac import entries, replace
from sdr.rf_catalog import software_profiles,validate_b3_floor


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(command, env=None):
    subprocess.run([str(x) for x in command], cwd=ROOT, env=env, check=True)


def check_uimage(data):
    header = bytearray(data[:64])
    magic, stored, _, size = struct.unpack_from('>4I', header)
    struct.pack_into('>I', header, 4, 0)
    if (magic != 0x27051956 or size != len(data)-64 or stored != zlib.crc32(header)&0xffffffff or
            struct.unpack_from('>I', data, 24)[0] != zlib.crc32(data[64:])&0xffffffff):
        raise ValueError('AP uImage integrity differs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=ROOT/'work/receiver-build')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'outputs/firmware/candidate')
    parser.add_argument('--bw0-cp-build',type=Path,help='build_capture_bridge manifest to embed in the real BW0 service')
    parser.add_argument('--experimental-pre-selector',type=int,choices=(6,7),
                        help='explicitly integrate matching finite unknown-rate CP experiment')
    parser.add_argument('--experimental-pre-switch',action='store_true',help='integrate finite switchable PRE5/6/7 experiment')
    parser.add_argument('--experimental-fem-override',action='store_true',help='integrate guarded stopped-only FEM template override operation53')
    parser.add_argument('--experimental-b3-min-hz',type=int,help='explicitly match the CP manual B3 experiment floor')
    parser.add_argument('--appimg-only',action='store_true',help='compile/link only, without packaging another PAC')
    parser.add_argument('--verify-lossy-ap',action='store_true',help='compile-only experimental six-slot AP; never package a PAC')
    parser.add_argument('--experimental-lossy-scratch',action='store_true',help='explicitly build a matched six-output-slot scratch experiment for manual flash; physical DMA/FIFO/cache unverified')
    parser.add_argument('--usb-baseline',type=Path,
                        help='completed 60-second fixed-source hardware report, required for BW0 PAC packaging')
    parser.add_argument('--revision',type=int,default=1,help='candidate file revision; API identity is unchanged')
    parser.add_argument('--unrestricted-frequency',action='store_true',help='remove manual-route frequency envelopes; uint32 Hz/100 Hz format remains')
    args = parser.parse_args()
    if args.unrestricted_frequency and args.experimental_b3_min_hz is not None:
        parser.error('choose unrestricted frequency or bounded B3 experiment')
    validate_b3_floor(args.experimental_b3_min_hz)
    if args.experimental_b3_min_hz is not None and not args.bw0_cp_build:
        parser.error('B3 extension requires matching CP build')
    if args.unrestricted_frequency and not args.bw0_cp_build:
        parser.error('unrestricted frequency requires matching CP build')
    if args.experimental_fem_override and not args.bw0_cp_build:
        parser.error('FEM override requires matching CP build')
    if args.verify_lossy_ap and (not args.appimg_only or not args.bw0_cp_build):
        parser.error('lossy AP verification requires --appimg-only and matching experimental CP manifest')
    if args.experimental_lossy_scratch and (args.verify_lossy_ap or not args.bw0_cp_build):
        parser.error('choose experimental scratch packaging or compile-only verification with a matching CP manifest')
    lossy_ap=args.verify_lossy_ap or args.experimental_lossy_scratch
    build, output = args.build_dir.resolve(), args.output_dir.resolve()
    if not build.is_relative_to(ROOT/'work') or not output.is_relative_to(ROOT/'outputs/firmware'):
        parser.error('choose build/output directories inside work and outputs/firmware')
    protected = {ROOT/'outputs/firmware/current'}
    state = json.loads((ROOT/'docs/project-state.json').read_text(encoding='utf-8'))
    protected.add((ROOT/state['installed_firmware']['pac']).parent.resolve())
    if output in protected:
        parser.error('never overwrite installed firmware')
    if not 1<=args.revision<=999:
        parser.error('revision must be in 1..999')
    pac_name=('Air724U_UIS8910_SDR_BW0_USB_v' if args.bw0_cp_build else 'Air724U_UIS8910_SDR_RawUSB_v')+str(args.revision)+'.pac'
    if not args.appimg_only and (output/pac_name).exists():
        parser.error('choose a new output directory for a new candidate')
    if args.bw0_cp_build and not args.appimg_only:
        if not args.usb_baseline:
            parser.error('BW0 packaging requires --usb-baseline with the fixed-source hardware result')
        evidence=json.loads(args.usb_baseline.read_text(encoding='utf-8'))
        if (evidence.get('source')!='fixed_ap_buffer_benchmark' or
                evidence.get('config',{}).get('duration_ms',0)<60000 or
                not evidence.get('transport_completed') or not evidence.get('requested_duration_reached') or
                evidence.get('status') not in ('passed','completed_with_loss') or evidence.get('cleanup_errors')):
            raise ValueError('fixed-source 60-second hardware evidence is incomplete')
    build.mkdir(parents=True, exist_ok=True)
    generated = build/'generated'
    generated.mkdir(exist_ok=True)
    cp=None
    max_bw=0
    if args.bw0_cp_build:
        cp=json.loads(args.bw0_cp_build.read_text(encoding='utf-8'))
        if bool(cp.get('unrestricted_frequency'))!=args.unrestricted_frequency:
            raise ValueError('AP/CP unrestricted frequency settings differ')
        if cp.get('experimental_b3_min_hz')!=args.experimental_b3_min_hz:
            raise ValueError('B3 experimental AP/CP floors must match explicitly')
        if args.experimental_b3_min_hz is not None and cp.get('rf_software_profiles')!=json.loads(json.dumps(software_profiles(args.experimental_b3_min_hz))):
            raise ValueError('B3 experimental CP software envelopes differ')
        if bool(cp.get('experimental_fem_override'))!=args.experimental_fem_override:
            raise ValueError('FEM override requires explicit matching AP/CP integration')
        if cp.get('experimental_lossy_scratch') and not lossy_ap:
            raise ValueError('lossy scratch CP is not ready for AP packaging; matching geometry and DMA validation required')
        if lossy_ap and not cp.get('experimental_lossy_scratch'):
            raise ValueError('lossy AP verification requires the scratch CP')
        if lossy_ap and cp.get('slot_bytes')!=8192:
            raise ValueError('scratch AP requires reviewed 8192-byte geometry')
        if bool(cp.get('experimental_pre_switch'))!=args.experimental_pre_switch:
            raise ValueError('switchable PRE CP requires explicit matching AP integration')
        if args.experimental_pre_switch and (args.experimental_pre_selector is not None or cp.get('until_stop_supported')):
            raise ValueError('switchable PRE is finite only and cannot combine with a fixed selector')
        selector=cp.get('experimental_bw5_pre_selector')
        if selector is not None and (selector!=args.experimental_pre_selector or cp.get('until_stop_supported')):
            raise ValueError('experimental CP PRE selector has unknown rate; standard AP/nominal-rate integration is not permitted')
        if args.experimental_pre_selector is not None and selector!=args.experimental_pre_selector:
            raise ValueError('AP and CP experimental selectors must match explicitly')
        bandwidths=cp.get('bandwidth_indices',[0])
        if bandwidths not in ([0],[0,1],[0,1,2],[0,1,2,3],[0,1,2,3,4],[0,1,2,3,4,5]):
            raise ValueError('unsupported CP bandwidth capability')
        max_bw=max(bandwidths)
        if not cp.get('native_restart_implemented') or not cp.get('precapture_config_implemented') or not cp.get('multi_profile_implemented'):
            raise ValueError('BW0 AP requires CP native REARM and pre-capture configuration support; rebuild CP modules')
        if cp.get('rf_profiles')!=list(software_profiles()):
            raise ValueError('BW0 CP RF profiles differ from AP advertised profiles; rebuild matching CP modules')
        blobs={}
        for name in ('resident','control'):
            data=(ROOT/cp[name]['path']).read_bytes()
            if sha(data)!=cp[name]['sha256']:
                raise ValueError('CP module input changed: '+name)
            blobs[name]=data
        if len(blobs['resident'])>0x4000 or len(blobs['control'])>0x2000:
            raise ValueError('CP module reservation exceeded')
        package=json.loads((ROOT/cp['control']['package']).read_text(encoding='utf-8'))
        lines=['#define SDR_BW0_CONTROL_ENTRY_OFFSET '+str(package['entry_offset'])+'u',
            '#define SDR_BW0_GENERATION '+cp['generation']+'u']
        for name,data in blobs.items():
            lines.append('static const unsigned char sdr_bw0_'+name+'_blob[] __attribute__((aligned(32)))={'+
                ','.join(hex(x) for x in data)+'};')
        (generated/'bw0_service_blob.h').write_text('\n'.join(lines)+'\n')
        (generated/'rf_profiles_info.h').write_text('#define SDR_RF_PROFILES_JSON '+
            json.dumps(json.dumps(cp['rf_profiles'],separators=(',',':')))+'\n'+
            '#define SDR_BW_INDICES_JSON '+json.dumps(json.dumps(bandwidths,separators=(',',':')))+'\n')
        (generated/'cp_transport_binding.h').write_text('#define CP_USB_MAILBOX '+cp['ap_mailbox']+'u\n'+
            '#define CP_USB_GENERATION '+cp['generation']+'u\n'+
            '#define CP_USB_PROGRESS 0x8096fec0u\n#define CP_USB_EXPORT 0x8096fa40u\n')
    state = json.loads((ROOT/'docs/project-state.json').read_text(encoding='utf-8'))
    baseline = ROOT/state['installed_firmware']['pac']
    base = baseline.read_bytes()
    if sha(base) != state['installed_firmware']['sha256']:
        raise ValueError('installed PAC file changed')
    base_entries = entries(base)
    sdk_elf = SDK/'core/iot_SDK_720U_map/CSDK_RDA8910.elf'
    abi = inspect(sdk_elf, baseline)
    (build/'udc-abi.json').write_text(json.dumps(abi, indent=2)+'\n', encoding='utf-8')
    functions = {f['name']:f for f in abi['functions']}
    bindings = {
        'COPS_ADD_FUNCTION':'copsAddFunction', 'COPS_ASSIGN_INTERFACE':'copsAssignInterface',
        'COPS_GET_CTRL':'copsGetCtrl', 'DRV_USB_DISABLE':'drvUsbDisable',
        'DRV_USB_ENABLE':'drvUsbEnable', 'PRV_DWC_EP_QUEUE':'prvDwcEpQueue'}
    lines = ['/* Generated from SDK ELF; each selected function matches the input PAC. */',
             '#define SDR_USB_GLOBAL 0x809b6c70u']
    for macro, name in bindings.items():
        function = functions[name]
        if not function['same_address_pac_bytes_match']:
            raise ValueError('SDK/PAC function differs: '+name)
        lines.append('#define SDR_ADDR_'+macro+' '+function['address']+'u')
    prefix = bytes.fromhex(functions['prvDwcEpQueue']['sdk_prefix'])
    lines.append('#define SDR_QUEUE_PREFIX {'+','.join(hex(x) for x in prefix)+'}')
    (generated/'udc_bindings.h').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    tools = SDK/'prebuilts/win32'
    gcc_dir = tools/'gcc-arm-none-eabi/bin'
    executable = '.exe' if os.name == 'nt' else ''
    gcc = gcc_dir/('arm-none-eabi-gcc'+executable) if os.name == 'nt' else Path(shutil.which('arm-none-eabi-gcc') or '')
    objcopy = gcc.with_name('arm-none-eabi-objcopy'+executable)
    common = [gcc, '-mcpu=cortex-a5', '-mthumb', '-mfloat-abi=soft', '-Os',
              '-ffreestanding', '-fno-builtin', '-fno-stack-protector']
    run(common+['-nostdlib', '-Wl,--build-id=none', '-Wl,-T,'+str(ROOT/'firmware/debug_monitor/cp_agent.ld'),
                ROOT/'firmware/debug_monitor/cp_agent.c', '-o', build/'cp_agent.elf'])
    run([objcopy, '-O', 'binary', build/'cp_agent.elf', build/'cp_agent.bin'])
    agent = (build/'cp_agent.bin').read_bytes()
    if not 0 < len(agent) <= 0x4000:
        raise ValueError('CP agent exceeds its reservation')
    (generated/'cp_agent_blob.h').write_text('static const unsigned char cp_agent_blob[] = {\n'+
        ','.join(hex(x) for x in agent)+'\n};\n', encoding='utf-8')
    template = ROOT/'firmware/sdr_receiver/CMakeLists.txt'
    integration = SDK/'demo/sdr_receiver/CMakeLists.txt'
    ownership=ROOT/'work/sdk-service-bridge.json'
    if integration.exists() and integration.read_bytes() != template.read_bytes():
        owned=(ownership.exists() and json.loads(ownership.read_text()).get('sha256')==sha(integration.read_bytes()))
        if not owned:
            raise ValueError('SDK service bridge has independent edits')
    integration.parent.mkdir(parents=True, exist_ok=True)
    integration.write_bytes(template.read_bytes())
    ownership.write_text(json.dumps({'sha256':sha(integration.read_bytes())})+'\n')
    env = dict(os.environ, BUILD_TARGET='sdr_receiver', CSDK_PRO='sdr_receiver',
               CSDK_VER='1.0.0', AM_MODEL='iot_SDK_720U')
    if os.name == 'nt':
        shim = build/'bin'
        shim.mkdir(exist_ok=True)
        # CMake 3.x resolves python3.exe before a .cmd shim and otherwise hits
        # the Windows Store execution alias. A local executable plus explicit
        # Python home selects the interpreter running this builder.
        shutil.copy2(sys.executable, shim/'python3.exe')
        env['PYTHONHOME'] = str(Path(sys.executable).parent)
        env['PATH'] = os.pathsep.join(map(str, (shim, gcc_dir, tools/'bin', Path(sys.executable).parent)))+os.pathsep+env['PATH']
        cmake, ninja = tools/'cmake/bin/cmake.exe', tools/'bin/ninja.exe'
    else:
        cmake, ninja = 'cmake', 'ninja'
    cmake_dir = build/'csdk'
    if (args.experimental_pre_selector is not None or args.experimental_pre_switch) and not cp:
        raise ValueError('experimental selector requires a matching CP manifest')
    flags = '-Wno-error=implicit-function-declaration -Wno-error=incompatible-pointer-types'
    if args.experimental_b3_min_hz is not None:
        flags+=' -DRXCAPT_EXPERIMENTAL_B3_MIN_RAW='+str(args.experimental_b3_min_hz//100)+'u'
    if args.unrestricted_frequency:
        flags+=' -DRXCAPT_UNRESTRICTED_FREQUENCY=1'
    if args.experimental_fem_override:
        flags+=' -DSDR_EXPERIMENTAL_FEM_OVERRIDE=1'
    if lossy_ap:
        flags+=' -DSDR_BW0_LOSSY_SCRATCH=1 -DSDR_RX_OUTPUT_SLOTS=6u'
    slot_bytes=cp.get('slot_bytes',8000) if cp else 8000
    if slot_bytes not in (8000,8192):
        raise ValueError('unsupported CP slot geometry')
    if cp and cp.get('rf_status_trace',{}).get('enabled'):
        from sdr.capture_layout import validate
        feature=cp['rf_status_trace']
        expected_address=0x8096e000 if slot_bytes==8192 else 0x8096dc00
        if int(feature['address'],0)!=expected_address or feature['bytes'] not in (256,512):
            raise ValueError('unsupported RF trace geometry')
        validate(0x80960000,slot_bytes,7,slot_bytes//4-1,0x8096e300,expected_address,feature['bytes'],
                 reserved=[('digital profile',0x8096e200,64)])
    if slot_bytes!=8000:
        flags+=' -DRXCAPT_FINITE_DATA_BYTES='+str(slot_bytes)+'u'
        flags+=' -DRXCAPT_FINITE_CAPTURE_END_ADDRESS='+str(slot_bytes//4-1)+'u'
    if args.experimental_pre_selector is not None:
        flags+=' -DSDR_EXPERIMENTAL_BW5_PRE_SELECTOR='+str(args.experimental_pre_selector)
    if args.experimental_pre_switch:
        flags+=' -DSDR_EXPERIMENTAL_PRE_SWITCH=1'
    run([cmake, '-S', SDK, '-B', cmake_dir, '-G', 'Ninja', '-DCMAKE_C_FLAGS='+flags,
         '-DSDR_GENERATED_DIR='+generated.as_posix(),'-DSDR_ENABLE_BW0_USB='+('ON' if cp else 'OFF'),
         '-DSDR_BW0_MAX_BW='+str(max_bw),
         '-DSDR_BW0_CONTINUOUS='+str(int(bool(cp and cp.get('until_stop_supported')))),
         '-DCP_USB_COMBINED_EXCHANGE='+str(int(bool(cp and cp.get('combined_exchange_supported'))))], env)
    target = 'Air720U_V403028_CSDK_demo_sdr_receiver'
    run([ninja, '-C', cmake_dir, target], env)
    image = (cmake_dir/'hex'/f'{target}.img').read_bytes()
    with (cmake_dir/'hex'/f'{target}.elf').open('rb') as stream:
        elf = ELFFile(stream)
        symbols = elf.get_section_by_name('.symtab')
        def address(name):
            rows = symbols.get_symbol_by_name(name)
            if not rows or len(rows) != 1:
                raise ValueError('missing/duplicate APPIMG symbol: '+name)
            return rows[0]['st_value']
        at_filter, abort_gate, test_ram = map(address, ['debug_at_write_filter','debug_data_abort_gate','test_ram'])
        ram_end = address('__ram_end')
    if not 0x60180000 <= at_filter < 0x60300000 or not at_filter&1 or abort_gate&3:
        raise ValueError('APPIMG hook addresses violate ABI')
    if cp and (hex(test_ram)!=cp['ap_mailbox'] or sha(agent)!=cp['cp_agent_sha256']):
        raise ValueError('BW0 AP/CP binding differs: actual mailbox '+hex(test_ram)+', agent '+sha(agent))
    if args.appimg_only or cp:
        sources=list((ROOT/'firmware/sdr_receiver').glob('*.[ch]'))
        if cp:
            sources += [ROOT/'firmware/capture/rxcapt_profile.h',ROOT/'firmware/capture/rxcapt_profile.c',args.bw0_cp_build.resolve(),
                        ROOT/cp['resident']['path'],ROOT/cp['control']['path'],generated/'rf_profiles_info.h']
        sources += [ROOT/'firmware/debug_monitor'/name for name in ('ap_monitor.c','ap_access.S','debug_hash.c','cp_agent.c','debug_shared.h')]
        report=dict(status='linked_appimg_not_packaged_or_deployed',device_accessed=False,hardware_tested=False,
            identity='uis8910-sdr-bw0-usb-v1' if cp else 'uis8910-sdr-raw-usb-v1',
            appimg=(cmake_dir/'hex'/f'{target}.img').relative_to(ROOT).as_posix(),appimg_sha256=sha(image),
            elf=(cmake_dir/'hex'/f'{target}.elf').relative_to(ROOT).as_posix(),
            ap_mailbox=hex(test_ram),ram_end=hex(ram_end),cp_modules=str(args.bw0_cp_build) if cp else None,
            integrated_ap_task=bool(cp),reset_free_rf_restart_implemented=bool(cp),reset_free_rf_restart_hardware_verified=False,
            rf_profiles=cp['rf_profiles'] if cp else [],bandwidth_indices=list(range(max_bw+1)) if cp else [],
            until_stop_supported=bool(cp and cp.get('until_stop_supported')),combined_exchange_supported=bool(cp and cp.get('combined_exchange_supported')),
            experimental_bw5_pre_selector=args.experimental_pre_selector,
            experimental_pre_switch=args.experimental_pre_switch,
            experimental_fem_override=args.experimental_fem_override,
            experimental_b3_min_hz=args.experimental_b3_min_hz,
        unrestricted_frequency=args.unrestricted_frequency,
            experimental_bw5_sample_rate_hz=None,
            dependencies={p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in sources+[template,Path(__file__)]})
        (build/'appimg-build.json').write_text(json.dumps(report,indent=2)+'\n')
        if args.appimg_only:
            print(json.dumps(report,indent=2)); return
    ap = bytearray(base_entries['8915DM_cat1_CSDK.img']['data'])
    check_uimage(ap)
    if ap[0x13164:0x13168] != bytes.fromhex('dff800f0') or ap[0x1316c:0x1316e] != bytes.fromhex('00bf'):
        raise ValueError('installed AT filter hook differs')
    ap[0x13164:0x1316e] = bytes.fromhex('dff800f0')+struct.pack('<I', at_filter)+bytes.fromhex('00bf')
    struct.pack_into('<I', ap, 0x3e0, abort_gate)
    struct.pack_into('>I', ap, 24, zlib.crc32(ap[64:])&0xffffffff)
    struct.pack_into('>I', ap, 4, 0)
    struct.pack_into('>I', ap, 4, zlib.crc32(ap[:64])&0xffffffff)
    check_uimage(ap)
    app_name = 'Air720U_V403028_CSDK_demo_debug_monitor.img'
    candidate = replace(base, {'8915DM_cat1_CSDK.img':bytes(ap), app_name:image})
    after = entries(candidate)
    changed = [n for n in after if after[n]['data'] != base_entries[n]['data']]
    # Hook targets may stay at identical addresses across builds. Requiring
    # the AP system image to change rejects a valid APPIMG-only update.
    if set(after)!=set(base_entries) or app_name not in changed or set(changed)-{'8915DM_cat1_CSDK.img',app_name}:
        raise ValueError('unexpected PAC payload changes')
    output.mkdir(parents=True, exist_ok=True)
    pac = output/pac_name
    pac.write_bytes(candidate)
    sources = list((ROOT/'firmware/sdr_receiver').glob('*.[ch]'))
    sources += [ROOT/'firmware/debug_monitor'/name for name in ('ap_monitor.c','ap_access.S','debug_hash.c','cp_agent.c','debug_shared.h')]
    sources += [Path(__file__), ROOT/'tools/usb/pac.py', template]
    if cp:
        sources += list((ROOT/'firmware/capture').glob('*'))
        sources += list((ROOT/'firmware/rf_rebuild').glob('*.[ch]'))
        sources += [generated/'rf_profiles_info.h']
        sources += [args.bw0_cp_build.resolve(),ROOT/cp['resident']['path'],ROOT/cp['control']['path'],
                    ROOT/cp['control']['package']]
        sources += [ROOT/path for path in cp.get('generated_bindings',{})]
    sources = sorted(set(p.resolve() for p in sources if p.is_file()))
    for path in sources:
        if not path.is_relative_to(ROOT):
            raise ValueError('source snapshot input escapes project')
        destination=output/'source-snapshot'/path.relative_to(ROOT)
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,destination)
    report = dict(status='built_candidate_for_manual_flash', hardware_tested=False, flashed=False,
        firmware_identity='uis8910-sdr-bw0-usb-v1' if cp else 'uis8910-sdr-raw-usb-v1', pac=str(pac.relative_to(ROOT)), sha256=sha(candidate),
        bytes=len(candidate), base_pac=str(baseline.relative_to(ROOT)), base_sha256=sha(base),
        changed_entries=changed, unchanged_cp_rf_nv_boot=True, data_source='bw0_capture' if cp else 'fixed_ap_buffer_benchmark',
        iq_capture_supported_by_this_candidate=bool(cp), ap_test_ram=hex(test_ram), app_ram_end=hex(ram_end),
        appimg_sha256=sha(image), ap_system_sha256=sha(ap), cp_agent_bytes=len(agent), cp_agent_sha256=sha(agent),
        winusb_guid='{5D6BCE91-4F8A-4D42-9A0D-A9E6F8AC8910}',
        control_operations=(dict(status=44,start=45,stop=46,configure=47,recovery=48) if cp else dict(status=40,start=41,stop=42)),
        build_directory=str(build.relative_to(ROOT)),
        elf=(cmake_dir/'hex'/f'{target}.elf').relative_to(ROOT).as_posix(),
        elf_sha256=sha((cmake_dir/'hex'/f'{target}.elf').read_bytes()),
        cp_modules=args.bw0_cp_build.resolve().relative_to(ROOT).as_posix() if cp else None,
        rf_profiles=cp['rf_profiles'] if cp else [],
        until_stop_supported=bool(cp and cp.get('until_stop_supported')),
        experimental_lossy_scratch=bool(cp and cp.get('experimental_lossy_scratch')),
        output_slots=6 if lossy_ap else 7,
        experimental_bw5_pre_selector=args.experimental_pre_selector,
        experimental_pre_switch=args.experimental_pre_switch,
        experimental_fem_override=args.experimental_fem_override,
        experimental_b3_min_hz=args.experimental_b3_min_hz,
        unrestricted_frequency=args.unrestricted_frequency,
        experimental_bw5_sample_rate_hz=None,
        usb_baseline_evidence=args.usb_baseline.resolve().relative_to(ROOT).as_posix() if cp else None,
        source_snapshot=(output/'source-snapshot').relative_to(ROOT).as_posix(),
        source_sha256={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in sources})
    (output/'build.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
