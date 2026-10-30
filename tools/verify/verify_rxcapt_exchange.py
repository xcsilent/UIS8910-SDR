"""Test combined CP ring exchange; no mailbox integration or device access."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    build=ROOT/'work/rxcapt-exchange';build.mkdir(exist_ok=True)
    source=ROOT/'firmware/capture/rxcapt_stream_batch.c';header=source.with_suffix('.h')
    harness=ROOT/'tools/verify/rxcapt_exchange_harness.c';exe=build/'exchange'
    subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-fsanitize=undefined',
        '-fno-sanitize-recover=all',str(source),str(harness),'-o',str(exe)],check=True)
    result=subprocess.check_output([str(exe)],text=True).strip()
    report=dict(status='passed',device_accessed=False,hardware_tested=False,result=result,
        mailbox_integrated=False,AP_integrated=False,
        scope='actual combined ring metadata primitive; exhaustive small occupancy/ownership/wrap matrix and malformed cases under UBSan. No CP poller concurrency, mailbox duplicate response, DMA/cache or throughput proof.',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,header,harness,Path(__file__))})
    output=ROOT/'records/usb/bw2-v7-exchange-core-verification.json';output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
