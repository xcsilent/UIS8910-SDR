"""Compile/test the optional CP-to-USB batch bridge without device access."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]


def verify(output):
    build=ROOT/'work/cp-usb-bridge'
    build.mkdir(parents=True,exist_ok=True)
    sdr=ROOT/'firmware/sdr_receiver'
    capture=ROOT/'firmware/capture'
    sources=[sdr/'iq_usb_ring.c',sdr/'cp_capture_bridge.c',capture/'rxcapt_stream_batch.c',
             ROOT/'tools/verify/cp_capture_bridge_harness.c']
    command=['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror',
        '-fsanitize=undefined','-fno-sanitize-recover=all','-I'+str(sdr),'-I'+str(capture)]
    executable=build/'bridge-test'
    subprocess.run(command+list(map(str,sources))+['-o',str(executable)],check=True)
    result=subprocess.check_output([str(executable)],text=True).strip()
    objects=[]
    for source in sources[1:3]:
        obj=build/(source.stem+'.o')
        subprocess.run(['arm-none-eabi-gcc','-mcpu=cortex-a5','-mthumb','-mfloat-abi=soft',
            '-std=c11','-O2','-Wall','-Wextra','-Werror','-ffreestanding','-fno-builtin',
            '-I'+str(sdr),'-I'+str(capture),'-c',str(source),'-o',str(obj)],check=True)
        objects.append(obj.relative_to(ROOT).as_posix())
    recipe=json.loads((capture/'build-recipe.json').read_text(encoding='utf-8'))
    tokens=recipe['commands'][0]
    command=[]
    for item in tokens:
        if isinstance(item,str):
            if item=='-lgcc':
                command.extend(['-DRXCAPT_USB_BATCH=1',str(capture/'rxcapt_stream_batch.c')])
            command.append(item)
        else:
            path=item['path']
            if not command:
                command.append('arm-none-eabi-gcc')
            elif path=='work/capture-build/resident.elf':
                command.append(str(build/'resident-batch.elf'))
            else:
                command.append(item['prefix']+str(ROOT/path))
    subprocess.run(command,cwd=ROOT,check=True)
    subprocess.run(['arm-none-eabi-objcopy','-O','binary',str(build/'resident-batch.elf'),str(build/'resident-batch.bin')],check=True)
    resident=build/'resident-batch.bin'
    if resident.stat().st_size>0x4000:
        raise ValueError('CP resident exceeded reserved executable window')
    dependencies=sources+[sdr/'cp_capture_bridge.h',capture/'rxcapt_stream_batch.h',capture/'rf_terminal_service.c']
    report=dict(status='passed',device_accessed=False,hardware_tested=False,host_test=result,
        arm_objects=objects,cp_batch_service_build=dict(path=resident.relative_to(ROOT).as_posix(),
            bytes=resident.stat().st_size,sha256=hashlib.sha256(resident.read_bytes()).hexdigest(),
            mailbox_bound_to_old_capture_profile=True,deployable_to_raw_usb_candidate=False),
        payload_copies=0,application_crc=False,
        scope='CP batch operations 11/12 and AP slot-ownership bridge tested; new AP mailbox/control binding, cache integration and live DMA still pending',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies})
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    verify(args.output)
