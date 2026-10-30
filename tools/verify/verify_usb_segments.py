"""Production UDC adapter profiling with synthetic time; no hardware access."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    build=ROOT/'work/usb-segments';build.mkdir(exist_ok=True)
    paths=['firmware/sdr_receiver/usb_segment_profile.c','firmware/sdr_receiver/iq_udc_adapter.c',
        'firmware/sdr_receiver/iq_usb_ring.c','tools/verify/usb_segment_profile_harness.c']
    exe=build/'segments'
    subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-DSDR_USB_SEGMENT_PROFILE=1',
        '-I'+str(ROOT/'firmware/sdr_receiver'),'-fsanitize=undefined','-fno-sanitize-recover=all',
        *[str(ROOT/p) for p in paths],'-o',str(exe)],check=True)
    result=subprocess.check_output([str(exe)],text=True).strip()
    paths+=['firmware/sdr_receiver/usb_segment_profile.h','firmware/sdr_receiver/iq_udc_adapter.h',
        'firmware/sdr_receiver/iq_usb_ring.h','firmware/sdr_receiver/usb_queue_observer.h','tools/verify/iq_udc_adapter_harness.c',
        'tools/verify/verify_usb_segments.py']
    report=dict(status='passed',hardware_tested=False,device_accessed=False,result=result,
        scope='actual profile aggregator and UDC adapter with fake clock/controller; timing overhead and physical completion latency unmeasured, control/AP integration not yet verified',
        dependencies={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths})
    out=ROOT/'records/usb/bw2-v8-segment-profile-verification.json';out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
