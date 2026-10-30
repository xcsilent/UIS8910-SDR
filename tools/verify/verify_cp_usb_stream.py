"""Validate the nonblocking AP CP-to-UDC worker with the actual CP batch core."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    build=ROOT/'work/cp-usb-stream'
    build.mkdir(parents=True,exist_ok=True)
    sdr=ROOT/'firmware/sdr_receiver'
    capture=ROOT/'firmware/capture'
    sources=[sdr/name for name in ('iq_usb_ring.c','iq_udc_adapter.c','cp_capture_bridge.c',
        'cp_stream_mailbox.c','cp_usb_stream.c','cp_usb_stream_snapshot.c')]
    sources+=[capture/'rxcapt_stream_batch.c',ROOT/'tools/verify/cp_usb_stream_harness.c']
    command=['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-fsanitize=undefined',
        '-fno-sanitize-recover=all','-I'+str(sdr),'-I'+str(capture)]
    combined_harness=ROOT/'tools/verify/cp_exchange_stream_harness.c'
    profile_source=sdr/'usb_segment_profile.c'
    # Retain historical geometry while testing the actual six-output-slot
    #8192B build. Scratch DMA itself is outside this AP/CP ownership harness.
    geometries=[]
    supply_harness=ROOT/'tools/verify/cp_supply_harness.c'
    for slots,size,end in ((7,8000,1999),(6,8192,2047)):
        definitions=['-DSDR_RX_OUTPUT_SLOTS='+str(slots),
            '-DRXCAPT_FINITE_DATA_BYTES='+str(size),
            '-DRXCAPT_FINITE_CAPTURE_END_ADDRESS='+str(end)]
        results={}
        for name,harness,flags in (
            ('separate',sources[-1],[]),
            ('combined',combined_harness,['-DCP_USB_COMBINED_EXCHANGE=1','-DSDR_USB_SEGMENT_PROFILE=1']),
            ('supply',supply_harness,['-DCP_USB_COMBINED_EXCHANGE=1'])):
            target=build/(name+'-'+str(slots)+'-'+str(size))
            inputs=sources[:-1]+[harness]+([profile_source] if name=='combined' else [])
            subprocess.run(command+definitions+flags+list(map(str,inputs))+['-o',str(target)],check=True)
            results[name]=subprocess.check_output([str(target)],text=True).strip()
        geometries.append(dict(output_slots=slots,slot_bytes=size,results=results))
    objects=[]
    for source in sources[3:6]:
        obj=build/(source.stem+'.o')
        subprocess.run(['arm-none-eabi-gcc','-mcpu=cortex-a5','-mthumb','-mfloat-abi=soft',
            '-std=c11','-O2','-Wall','-Wextra','-Werror','-ffreestanding','-fno-builtin',
            '-I'+str(sdr),'-c',str(source),'-o',str(obj)],check=True)
        objects.append(obj.relative_to(ROOT).as_posix())
    dependencies=sources+[combined_harness,supply_harness,capture/'rxcapt_finite_abi.h',capture/'rxcapt_stream_batch.h',profile_source,sdr/'usb_segment_profile.h']+[sdr/name for name in ('cp_stream_mailbox.h','cp_usb_stream.h',
        'cp_capture_bridge.h','iq_usb_ring.h','iq_udc_adapter.h','udc_8910.h')]+[Path(__file__)]
    report=dict(status='passed',device_accessed=False,hardware_tested=False,
        host_test=geometries[0]['results']['separate'],combined_exchange_test=geometries[0]['results']['combined'],
        geometries=geometries,
        arm_objects=objects,payload_cpu_access=False,application_crc=False,
        scope='Actual C components with fake CP scheduling/UDC, historical7x8000 and current6x8192 output geometry. Full-window refill event orders, not real-time throughput or prevalence. Scratch DMA, cache/MMU, RF lifecycle, linked AP integration and device CPU not modeled; ARM compile uses default geometry.',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
