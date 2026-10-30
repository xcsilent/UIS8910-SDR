"""Test experimental paired scratch metadata against production batch exchange."""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
names = ['firmware/capture/rxcapt_lossy_pair.c', 'firmware/capture/rxcapt_stream_batch.c',
         'tools/verify/cp_lossy_pair_harness.c']
paths = [root/name for name in names]
out = root/'work/cp-lossy-pair-test'
subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-fsanitize=undefined','-fno-sanitize-recover=all',
                '-I'+str(root/'firmware/capture'),*map(str,paths),'-o',str(out)],check=True)
result = subprocess.check_output([str(out)],text=True).strip()
arm = root/'work/cp-lossy-pair.o'
subprocess.run(['arm-none-eabi-gcc','-mcpu=cortex-a5','-mthumb','-mfloat-abi=soft',
                '-std=c11','-O2','-Wall','-Wextra','-Werror','-ffreestanding',
                '-c',str(paths[0]),'-o',str(arm)],check=True)
paths += [root/'firmware/capture/rxcapt_lossy_pair.h',root/'firmware/capture/rxcapt_stream_idle.h', Path(__file__)]
report = {'status':'passed', 'result':result, 'device_accessed':False, 'hardware_tested':False,
          'scope':'Experimental C metadata primitive composed with actual batch exchange on synthetic state; ARM compile only, no linked producer, DMA, memory/cache or RF proof.',
          'dependencies':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
(root/'records/usb/geometry-lossy-pair-primitive.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))
