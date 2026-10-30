"""Exercise production CP batch and AP bridge with six experimental slots."""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
names = ['firmware/capture/rxcapt_stream_batch.c', 'firmware/sdr_receiver/cp_capture_bridge.c',
         'firmware/sdr_receiver/iq_usb_ring.c', 'tools/verify/cp_six_slot_harness.c']
paths = [root/name for name in names]
output = root/'work/cp-six-slot-test'
command = ['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined',
           '-fno-sanitize-recover=all', '-DSDR_RX_OUTPUT_SLOTS=6',
           '-I'+str(root/'firmware/sdr_receiver'), '-I'+str(root/'firmware/capture'),
           *map(str, paths), '-o', str(output)]
subprocess.run(command, check=True)
result = subprocess.check_output([str(output)], text=True).strip()
snapshot = root/'work/cp-six-snapshot-test'
snapshot_sources = [root/'firmware/sdr_receiver/cp_usb_stream_snapshot.c',
                    root/'tools/verify/cp_six_snapshot_harness.c']
subprocess.run(command[:8] + ['-DSDR_RX_OUTPUT_SLOTS=6',
               '-I'+str(root/'firmware/sdr_receiver'), '-I'+str(root/'firmware/capture'),
               *map(str,snapshot_sources),'-o',str(snapshot)],check=True)
snapshot_result = subprocess.check_output([str(snapshot)],text=True).strip()
paths += snapshot_sources
paths += [root/'firmware/capture/rxcapt_finite_abi.h', Path(__file__)]
report = {'status':'passed', 'result':result, 'snapshot_result':snapshot_result, 'device_accessed':False, 'hardware_tested':False,
          'scope':'Actual CP batch and AP bridge, synthetic metadata and USB completion; no mailbox concurrency, DMA, cache or full CP build.',
          'dependencies':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
(root/'records/usb/geometry-six-slot-bridge.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
print(json.dumps(report, indent=2))
