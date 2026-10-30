"""Independent coherent-tone and known block phase-break checks; no hardware."""
import hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from rf_fft import compare

def main():
    rate=15360000;n=1024000;rng=np.random.default_rng(20261027)
    noise=rng.normal(0,1,n)+1j*rng.normal(0,1,n)
    tone=100*np.exp(2j*np.pi*150000*np.arange(n)/rate)
    coherent=compare(tone+noise,noise,rate,150000,[2000,32768])
    phase=np.repeat(rng.uniform(-np.pi,np.pi,n//2000),2000)
    broken=compare(tone*np.exp(1j*phase)+noise,noise,rate,150000,[2000,32768])
    assert all(abs(r['peak_error_hz'])<rate/2000 for r in coherent+broken)
    assert all(r['near_peak_on_off_db']>20 for r in coherent+broken)
    assert broken[-1]['main_peak_half_power_width_hz']>coherent[-1]['main_peak_half_power_width_hz']*3
    absent=compare(noise,noise,rate,150000,[32768])[0]
    assert abs(absent['near_peak_on_off_db'])<1e-9
    report=dict(status='passed',device_accessed=False,coherent=coherent,known_block_phase_breaks=broken,
        absent_on_off_db=absent['near_peak_on_off_db'],
        scope='Synthetic control proves FFT-size response, phase-break broadening and on/off rejection; not real loss positions or live refresh.',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__),ROOT/'tools/rf_fft.py',ROOT/'tools/sdr/artifacts.py']})
    (ROOT/'records/rf/wideband-fft-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status'])

if __name__=='__main__':main()
