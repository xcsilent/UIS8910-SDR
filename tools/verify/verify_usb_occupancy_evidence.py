"""Evaluate whether retained same-session USB statistics identify starvation."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
source = ROOT/'records/usb/geometry-v21-usb-segment-comparison.json'
record = json.loads(source.read_text(encoding='utf-8'))
row = next(row for row in record['rows'] if row['label'] == 'segment-on')
profile = record['segment_profile']
assert row['epoch'] == profile['epoch'] and profile['counter_snapshot_final']
stage = profile['stages']['submit_to_callback']
assert stage['count'] == profile['claimed_blocks'] and stage['count'] > 0
rate = row['steady_bytes_per_second']/8192
latency = stage['mean_elapsed_us']
result = dict(status='analyzed', device_accessed=False, hardware_tested=False,
    source=source.relative_to(ROOT).as_posix(), epoch=row['epoch'],
    throughput_bytes_per_second=row['steady_bytes_per_second'], block_bytes=8192,
    completion_latency_mean_us=latency, estimated_outstanding=rate*latency/1e6,
    scope='Approximate Little-law cross-check only: steady throughput and whole-session latency use different windows; queue includes the active DMA. This cannot establish empty-queue fraction, idle duration, or current v23 performance.',
    next_measurement='Count successful completions where no other request remains outstanding, excluding stop/error, and measure idle-to-next-submit duration. Define explicit ABI; count API acceptance separately from hardware-active state and include synchronous enqueue/reject/cancel tests.',
    dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),source)})
out=ROOT/'records/usb/occupancy-evidence.json'
out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
