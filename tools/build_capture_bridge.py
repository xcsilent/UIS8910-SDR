"""Build BW0 B5 batch-service RAM modules bound to the raw-USB AP candidate.

Does not load modules or access hardware. This prepares stage-2 inputs while
the user flashes/tests the stage-1 fixed-buffer USB firmware.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zlib

from elftools.elf.elffile import ELFFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/debug'))
from uis_debug import make_package
from sdr.rf_catalog import software_profiles,validate_b3_floor


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local(path):
    return ROOT/str(path).replace('\\','/')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ap-build',type=Path,help='explicit historical seed build (research only); current build uses --platform/--agent')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'work/raw-usb-bw0-batch')
    parser.add_argument('--ap-elf',type=Path,help='bind to test_ram from the newly linked AP ELF instead of the seed PAC')
    parser.add_argument('--platform',type=Path,help='current platform configuration; avoids historical seed PAC dependency')
    parser.add_argument('--agent',type=Path,help='freshly compiled CP agent, required with --platform')
    parser.add_argument('--compiler-bin',type=Path,help='relocatable ARM toolchain bin directory')
    parser.add_argument('--multi-profile',action='store_true',help='enable B3/B5/B8 and B40/A CP configuration; AP integration required')
    parser.add_argument('--experimental-b3-min-hz',type=int,help='manual B3 experiment floor in [1650,1710) MHz; matching AP/host required')
    parser.add_argument('--max-bandwidth-index',type=int,choices=(0,1,2,3,4,5),default=0,
        help='opt-in CP bandwidth capability; BW2..BW4 allow partial IQ and require matching AP/host integration, no deployment')
    parser.add_argument('--until-stop',action='store_true',help='renew CP watchdog on valid AP activity; requires matched AP control lease')
    parser.add_argument('--generation',type=lambda v:int(v,0),help='explicit paired AP/CP generation for a new candidate')
    parser.add_argument('--slot-bytes',type=int,choices=(8000,8192),default=8000,
        help='experimental capture slot size; 8192 requires a distinct generation; optional trace relocates beyond DATA')
    parser.add_argument('--lossy-scratch',action='store_true',help='build unlinked-for-deployment six-output scratch experiment; AP matching and DMA verification required')
    parser.add_argument('--rf-status-trace',action='store_true',help='opt-in fixed-count RF phase register observations; separate DDR, no IQ changes')
    parser.add_argument('--rf-status-dual-bank',action='store_true',help='opt-in trace ABI2: both calibration banks, route fields, BBPLL states; 512B DDR')
    parser.add_argument('--rf-status-fem',action='store_true',help='opt-in trace ABI3: copy saved RF RAM ID/target; no RFFE bus access; requires dual-bank trace')
    parser.add_argument('--rf-status-fem-execution',action='store_true',help='ABI5: matching cold-loaded RF observer entry count/pointer; replaces command-slot observations')
    parser.add_argument('--experimental-fem-override',action='store_true',help='guarded B5/B8 RF template byte experiment; CP CONFIG bits27:26, default off; matching AP integration required')
    parser.add_argument('--rf-status-fem-commands',action='store_true',help='opt-in ABI4 RX command-slot observations; requires FEM trace')
    parser.add_argument('--experimental-bw5-pre-selector',type=int,choices=(6,7),
        help='independent CP selector for RF mode5 only; unknown rate, finite experiments only, not standard AP integration')
    parser.add_argument('--experimental-pre-switch',action='store_true',help='experimental finite CP selection of PRE5/6/7 through stopped CONFIG')
    parser.add_argument('--unrestricted-frequency',action='store_true',help='remove manual-route frequency envelopes; uint32 Hz/100 Hz format remains')
    args=parser.parse_args()
    if args.unrestricted_frequency and args.experimental_b3_min_hz is not None:
        parser.error('choose unrestricted frequency or bounded B3 experiment')
    validate_b3_floor(args.experimental_b3_min_hz)
    if args.experimental_b3_min_hz is not None and (not args.multi_profile or not args.generation):
        parser.error('B3 extension requires multi-profile and a distinct explicit generation')
    if args.lossy_scratch and (args.slot_bytes!=8192 or not args.generation):
        parser.error('scratch experiment requires 8192-byte slots and distinct generation')
    if args.slot_bytes!=8000 and not args.generation:
        parser.error('8192-byte slots require a distinct generation')
    if args.rf_status_trace and not args.generation:
        parser.error('RF diagnostic requires a distinct explicit candidate generation')
    if args.rf_status_dual_bank and not args.rf_status_trace:
        parser.error('dual-bank diagnostic requires --rf-status-trace and explicit generation')
    if args.rf_status_fem and not args.rf_status_dual_bank:
        parser.error('FEM snapshot requires --rf-status-dual-bank and trace')
    if args.rf_status_fem_commands and not args.rf_status_fem:
        parser.error('command observations require --rf-status-fem')
    if args.rf_status_fem_execution and (not args.rf_status_fem or args.rf_status_fem_commands):
        parser.error('execution observations require FEM trace and exclude command-slot observations')
    if args.experimental_fem_override and (not args.rf_status_fem_execution or not args.multi_profile or args.experimental_pre_switch):
        parser.error('FEM override requires multi-profile, ABI5 execution trace and excludes PRE switching')
    if args.unrestricted_frequency and (not args.multi_profile or not args.generation):
        parser.error('unrestricted frequency requires multi-profile and explicit generation')
    trace_address=0x8096e000 if args.slot_bytes==8192 else 0x8096dc00
    if args.rf_status_trace:
        from sdr.capture_layout import validate
        validate(0x80960000,args.slot_bytes,7,args.slot_bytes//4-1,0x8096e300,
                 trace_address,512 if args.rf_status_dual_bank else 256,
                 reserved=[('digital profile',0x8096e200,64)])
    if args.experimental_pre_switch and args.experimental_bw5_pre_selector is not None:
        parser.error('choose either fixed selector or switchable experiment')
    if (args.experimental_bw5_pre_selector is not None or args.experimental_pre_switch) and (not args.generation or args.max_bandwidth_index!=5 or args.until_stop):
        parser.error('experimental PRE selector requires explicit generation, max BW5 and finite capture (no --until-stop)')
    directory=args.output_dir.resolve()
    if not directory.is_relative_to(ROOT/'work') or directory.exists():
        parser.error('choose a new output directory inside work')
    if args.platform:
        platform=json.loads(args.platform.read_text(encoding='utf-8'))
        if not args.agent:
            parser.error('--platform requires --agent')
        agent=args.agent.resolve()
        ap=dict(pac=None,sha256=None,ap_test_ram=platform['ap_mailbox'],
                cp_agent_sha256=platform['cp_agent_sha256'])
    else:
        if not args.ap_build:
            parser.error('use tools/build_firmware.py for the current release, or supply explicit --platform/--agent inputs')
        ap=json.loads(args.ap_build.read_text(encoding='utf-8'))
        if ap['firmware_identity']!='uis8910-sdr-raw-usb-v1' or sha(local(ap['pac']))!=ap['sha256']:
            raise ValueError('raw USB AP candidate identity differs')
        agent=local(ap['build_directory'])/'cp_agent.bin'
    if sha(agent)!=ap['cp_agent_sha256']:
        raise ValueError('AP CP agent input differs')
    mailbox=int(ap['ap_test_ram'],0)
    if args.ap_elf:
        with args.ap_elf.open('rb') as stream:
            symbols={s.name:s['st_value'] for s in ELFFile(stream).get_section_by_name('.symtab').iter_symbols()}
        mailbox=symbols['test_ram']
    if mailbox%32 or not 0x80f00000<=mailbox<0x80fff000:
        raise ValueError('new AP mailbox violates reviewed geometry')
    directory.mkdir(parents=True)
    bound_elf=None
    if args.ap_elf:
        bound_elf=directory/'ap-binding.elf'
        shutil.copy2(args.ap_elf,bound_elf)
    generated=directory/'generated'
    generated.mkdir()
    for path in (ROOT/'firmware/capture/generated').iterdir():
        if path.is_file():
            shutil.copy2(path,generated/path.name)
    binding=generated/'terminal_binding.h'
    content=binding.read_text(encoding='utf-8')
    generation=0x52550001+(args.max_bandwidth_index<<8)+(0x10000 if args.until_stop else 0)
    if args.generation is not None:
        if not 0<args.generation<=0xffffffff:parser.error('generation must be a nonzero uint32')
        generation=args.generation
    def replace_define(text,name,value):
        result,count=re.subn(r'(#define '+name+r')\s+[^\n]+',lambda m:m[1]+' '+value,text)
        if count!=1:
            raise ValueError('binding define is not unique: '+name)
        return result
    content=replace_define(content,'TERM_GENERATION',hex(generation)+'u')
    content=replace_define(content,'TERM_SERVICE_MAILBOX',hex(mailbox)+'u')
    binding.write_text(content,encoding='utf-8')
    (generated/'cp_agent_expected.h').write_text('static const unsigned char cp_agent_expected[]={'+
        ','.join(hex(x) for x in agent.read_bytes())+'};\n',encoding='utf-8')
    recipe=json.loads((ROOT/'firmware/capture/build-recipe.json').read_text(encoding='utf-8'))
    def command(index):
        result=[]
        for item in recipe['commands'][index]:
            if isinstance(item,str):
                if (args.rf_status_trace or args.slot_bytes!=8000) and item in ('-DRXCAPT_RF_CORE_SNAPSHOT=1','-DRXCAPT_RF_PHASE_LOG=1',
                        '-DRXCAPT_RF_CODE_SNAPSHOT=1','-DRXCAPT_RF_CALIBRATION_SNAPSHOT=1','-DRXCAPT_RF_SFR_SNAPSHOT=1'):
                    item=item[:-1]+'0' # Replace legacy diagnostics; never enlarge the resident reservation.
                if item=='-DRXCAPT_RAW_SWEEP_MIN=8815000u': item='-DRXCAPT_RAW_SWEEP_MIN=8690000u'
                if item=='-DRXCAPT_RAW_SWEEP_MAX=8815000u': item='-DRXCAPT_RAW_SWEEP_MAX=8939000u'
                if item=='-lgcc' and index==0:
                    result.extend(['-DRXCAPT_USB_BATCH=1','-DRXCAPT_REUSABLE_STREAM=1',
                        str(ROOT/'firmware/capture/rxcapt_stream_batch.c')])
                    if args.lossy_scratch:
                        result.append(str(ROOT/'firmware/capture/rxcapt_lossy_pair.c'))
                if item=='-lgcc' and index==0 and args.multi_profile:
                    result.append(str(ROOT/'firmware/capture/rxcapt_profile.c'))
                if item=='-lgcc' and index==0 and args.experimental_fem_override:
                    result.append(str(ROOT/'firmware/rf_rebuild/rf_frontend_override.c'))
                if item=='-mcpu=cortex-a5' and args.experimental_fem_override:
                    result.append('-DRXCAPT_EXPERIMENTAL_FEM_OVERRIDE=1')
                if item=='-mcpu=cortex-a5' and args.unrestricted_frequency:
                    result.append('-DRXCAPT_UNRESTRICTED_FREQUENCY=1')
                if item=='-mcpu=cortex-a5' and args.multi_profile:
                    result.append('-DRXCAPT_MULTI_PROFILE=1')
                if item=='-mcpu=cortex-a5' and args.experimental_b3_min_hz is not None:
                    result.append('-DRXCAPT_EXPERIMENTAL_B3_MIN_RAW='+str(args.experimental_b3_min_hz//100)+'u')
                if item=='-mcpu=cortex-a5' and args.lossy_scratch:
                    result.extend(['-DRXCAPT_LOSSY_SCRATCH=1','-DSDR_RX_OUTPUT_SLOTS=6u'])
                if item=='-mcpu=cortex-a5' and args.max_bandwidth_index:
                    result.append('-DRXCAPT_USB_MAX_BW='+str(args.max_bandwidth_index))
                if item=='-mcpu=cortex-a5' and args.until_stop:
                    result.append('-DRXCAPT_USB_UNTIL_STOP=1')
                if item=='-mcpu=cortex-a5' and args.rf_status_trace:
                    result.extend(['-DRXCAPT_RF_STATUS_TRACE=1','-DRF_STATUS_TRACE_ADDRESS='+hex(trace_address)+'u'])
                if item=='-mcpu=cortex-a5' and args.rf_status_dual_bank:
                    result.append('-DRXCAPT_RF_STATUS_DUAL_BANK=1')
                if item=='-mcpu=cortex-a5' and args.rf_status_fem:
                    result.append('-DRXCAPT_RF_STATUS_FEM=1')
                if item=='-mcpu=cortex-a5' and args.rf_status_fem_commands:
                    result.append('-DRXCAPT_RF_STATUS_FEM_COMMANDS=1')
                if item=='-mcpu=cortex-a5' and args.rf_status_fem_execution:
                    result.append('-DRXCAPT_RF_STATUS_FEM_EXECUTION=1')
                if item=='-mcpu=cortex-a5' and args.slot_bytes!=8000:
                    result.extend(['-DRXCAPT_FINITE_DATA_BYTES='+str(args.slot_bytes)+'u',
                                   '-DRXCAPT_FINITE_CAPTURE_END_ADDRESS='+str(args.slot_bytes//4-1)+'u'])
                if item=='-mcpu=cortex-a5' and args.experimental_bw5_pre_selector is not None:
                    result.append('-DRXCAPT_EXPERIMENTAL_BW5_PRE_SELECTOR='+str(args.experimental_bw5_pre_selector))
                if item=='-mcpu=cortex-a5' and args.experimental_pre_switch:
                    result.append('-DRXCAPT_EXPERIMENTAL_PRE_SWITCH=1')
                result.append(item)
                continue
            relative=item['path']
            if relative.startswith('firmware/capture/generated'):
                tail=Path(relative).relative_to('firmware/capture/generated')
                path=generated/tail
            elif relative.startswith('work/capture-build/'):
                path=directory/Path(relative).name
            else:
                path=ROOT/relative
            if args.compiler_bin and relative.startswith('inputs/repositories/') and '/bin/' in relative:
                path=args.compiler_bin.resolve()/Path(relative).name
            if not result and os.name!='nt':
                result.append(path.name.removesuffix('.exe'))
            else:
                result.append(item['prefix']+str(path))
        if index==2 and args.multi_profile:
            result.append(str(ROOT/'firmware/capture/rxcapt_profile.c'))
        return result
    def run(index):
        subprocess.run(command(index),cwd=ROOT,check=True)
    run(0);run(1)
    with (directory/'resident.elf').open('rb') as stream:
        symbols={s.name:s['st_value'] for s in ELFFile(stream).get_section_by_name('.symtab').iter_symbols()}
    resident=(directory/'resident.bin').read_bytes()
    combined_exchange='rxcapt_stream_exchange_batch' in symbols
    if len(resident)>0x4000:
        raise ValueError('resident code reservation exceeded')
    if symbols['rxcapt_finite_data_callback']&~1!=0x8097b078 or symbols['rxcapt_finite_head_callback']&~1!=0x8097b07c:
        raise ValueError('finite DMA callback binding changed')
    content=replace_define(content,'TERM_RESIDENT_BYTES',hex(len(resident))+'u')
    content=replace_define(content,'TERM_RESIDENT_CRC32',hex(zlib.crc32(resident)&0xffffffff)+'u')
    content=replace_define(content,'TERM_FOREGROUND_ENTRY',hex(symbols['terminal_foreground_entry']|1)+'u')
    binding.write_text(content,encoding='utf-8')
    # Updating the control's CRC/size constants must not alter the resident.
    run(0);run(1)
    if (directory/'resident.bin').read_bytes()!=resident:
        raise ValueError('resident binding did not reach a stable CRC/size')
    run(2);run(3)
    control=directory/'control.bin'
    with (directory/'control.elf').open('rb') as stream:
        symbols={s.name:s['st_value'] for s in ELFFile(stream).get_section_by_name('.symtab').iter_symbols()}
    make_package(control,directory/'control.json',symbols['terminal_control']|1,generation)
    report=dict(status='built_stage2_inputs_not_deployed',device_accessed=False,hardware_tested=False,
        ap_pac=ap['pac'] if not args.ap_elf else None,ap_pac_sha256=ap['sha256'] if not args.ap_elf else None,
        seed_ap_pac=ap['pac'],ap_elf=bound_elf.relative_to(ROOT).as_posix() if bound_elf else None,
        ap_elf_sha256=sha(bound_elf) if bound_elf else None,ap_mailbox=hex(mailbox),
        cp_agent_sha256=ap['cp_agent_sha256'],generation=hex(generation),
        profile=('/'.join('B'+str(b) for b in software_profiles()) if args.multi_profile else 'B5')+'; batch CLAIM/RELEASE 11/12, full-init REARM 9, FAST_TUNE disabled',
        native_restart_implemented=True,
        combined_exchange_supported=combined_exchange,
        precapture_config_implemented=True,
        multi_profile_implemented=args.multi_profile,
        rf_profiles=list(software_profiles()) if args.multi_profile else [5],
        experimental_b3_min_hz=args.experimental_b3_min_hz,
        rf_software_profiles=software_profiles(args.experimental_b3_min_hz,args.unrestricted_frequency),
        unrestricted_frequency=args.unrestricted_frequency,
        bandwidth_indices=list(range(args.max_bandwidth_index+1)),
        until_stop_supported=args.until_stop,
        slot_bytes=args.slot_bytes,
        experimental_lossy_scratch=args.lossy_scratch,
        experimental_bw5_pre_selector=args.experimental_bw5_pre_selector,
        experimental_pre_switch=args.experimental_pre_switch,
        experimental_fem_override=args.experimental_fem_override,
        experimental_bw5_sample_rate_hz=None,
        experimental_scope=('RF mode5 retained; CP PRE selector overridden, rate unknown; finite experimental integration required'
            if args.experimental_bw5_pre_selector is not None or args.experimental_pre_switch else None),
        rf_status_trace=dict(enabled=args.rf_status_trace,address=hex(trace_address),bytes=512 if args.rf_status_dual_bank else 256,abi=5 if args.rf_status_fem_execution else 4 if args.rf_status_fem_commands else 3 if args.rf_status_fem else 2 if args.rf_status_dual_bank else 1,
            dual_bank=args.rf_status_dual_bank,
            saved_fem_result=args.rf_status_fem,
            legacy_rf_snapshots_replaced=args.rf_status_trace,
            scope='five phase samples only; MMIO stalls not bounded; no hardware validation'),
        resident=dict(path=(directory/'resident.bin').relative_to(ROOT).as_posix(),bytes=len(resident),
                      sha256=sha(directory/'resident.bin'),crc32=hex(zlib.crc32(resident)&0xffffffff)),
        control=dict(path=control.relative_to(ROOT).as_posix(),bytes=control.stat().st_size,
                     sha256=sha(control),package=(directory/'control.json').relative_to(ROOT).as_posix()),
        limitation='Full native initialization on drained REARM is compiled, not hardware verified. These modules require the integrated BW0 service, not the fixed-buffer PAC or old mailbox.',
        generated_bindings={p.relative_to(ROOT).as_posix():sha(p) for p in generated.iterdir() if p.is_file()})
    (directory/'build.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
