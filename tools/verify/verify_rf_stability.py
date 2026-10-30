"""Known stationary and drifting tones with independent DMA block phases."""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from rf_stability import track


def main():
    rate = 30720000
    rng = np.random.default_rng(27)
    size = 2000
    groups = 4
    frequencies = np.repeat([142300., 144300., 146300., 148300.], 32)
    phase = rng.uniform(-np.pi, np.pi, len(frequencies))
    t = np.arange(size)/rate
    def signal(freq):
        z = 100*np.exp(1j*(2*np.pi*np.asarray(freq)[:, None]*t+phase[:, None]))
        return (z+rng.normal(size=z.shape)+1j*rng.normal(size=z.shape)).ravel()
    stationary = track(signal(np.full(len(frequencies),142300.)),rate,150000)
    drifting = track(signal(frequencies),rate,150000)
    assert len(drifting['groups']) == groups
    assert stationary['span_hz'] < 100
    errors = [r['peak_hz']-f for r,f in zip(drifting['groups'],frequencies[::32])]
    assert max(abs(e) for e in errors) < 100
    assert 5900 < drifting['span_hz'] < 6100
    # Current scratch firmware delivers2048-sample DMA blocks. Independent
    # block phases make using the legacy2000-sample geometry observably wrong.
    size=2048;t=np.arange(size)/rate
    current=track(signal(frequencies),rate,150000,dma_samples=size)
    current_errors=[r['peak_hz']-f for r,f in zip(current['groups'],frequencies[::32])]
    assert len(current['groups'])==groups and max(abs(e) for e in current_errors)<100
    for invalid in (0,2001,4096):
        try:track(np.zeros(65536),rate,150000,dma_samples=invalid)
        except ValueError:pass
        else:raise AssertionError('unsupported geometry accepted')
    report = dict(status='passed',device_accessed=False,stationary_span_hz=stationary['span_hz'],
                  drifting_estimation_errors_hz=errors,current2048_estimation_errors_hz=current_errors,
                  scope='Known synthetic frequencies with random per-block phase; not hardware calibration or absent-tone detection.',
                  dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in [Path(__file__),ROOT/'tools/rf_stability.py',ROOT/'tools/sdr/sample_rate.py',ROOT/'firmware/sdr_receiver/sample_rate.h']})
    (ROOT/'records/rf/b40-stability-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':main()
