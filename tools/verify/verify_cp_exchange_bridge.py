"""Compose production CP exchange and AP atomic commit; no mailbox/hardware."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    build=ROOT/'work/cp-exchange-bridge';build.mkdir(exist_ok=True)
    sources=[ROOT/p for p in ('firmware/capture/rxcapt_stream_batch.c','firmware/sdr_receiver/cp_capture_bridge.c',
        'firmware/sdr_receiver/iq_usb_ring.c','tools/verify/cp_exchange_bridge_harness.c')]
    exe=build/'bridge'
    subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all',*map(str,sources),'-o',str(exe)],check=True)
    result=subprocess.check_output([str(exe)],text=True).strip()
    deps=sources+[ROOT/'firmware/capture/rxcapt_stream_batch.h',ROOT/'firmware/sdr_receiver/cp_capture_bridge.h',ROOT/'firmware/sdr_receiver/iq_usb_ring.h',Path(__file__)]
    report=dict(status='passed',hardware_tested=False,device_accessed=False,mailbox_integrated=False,result=result,
        scope='production CP metadata exchange composed with AP reply commit under synthetic ownership/USB-completion states; no mailbox timing/replay, actual DMA/cache or throughput proof',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in deps})
    path=ROOT/'records/usb/bw2-v7-exchange-bridge-verification.json';path.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
