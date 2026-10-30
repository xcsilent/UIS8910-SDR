"""Diagnose retained reference IQ per DMA block; no device access or acceptance change."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def distribution(values):
    return dict(zip(('p05', 'median', 'p95'), map(float, np.percentile(values, (5, 50, 95)))))


def runs(mask):
    """Inclusive block-index runs, without inferring wall-clock timing."""
    edges = np.diff(np.r_[False, mask, False].astype(int))
    return [[int(a), int(b-1)] for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))]


def analyze(capture, rate):
    meta = capture['spectrum']
    n = meta['analysis_dma_samples']
    path = Path(capture['raw_path'])
    words = np.fromfile(path, dtype='<u4', count=meta['analysis_complex_samples'],
                        offset=meta['analysis_skip_complex_samples'] * 4)
    if len(words) != meta['analysis_complex_samples']:
        raise ValueError('retained analysis window is incomplete: ' + str(path))
    a = ((words & 65535).astype('<u2').view('<i2').astype(np.int32) >> 4).astype(float)
    b = ((words >> 16).astype('<u2').view('<i2').astype(np.int32) >> 4).astype(float)
    z = (a - 1j*b).reshape(-1, n)
    z -= z.mean(axis=1, keepdims=True)
    p = abs(np.fft.fft(z*np.hanning(n), n=8192, axis=1))**2
    hz = np.fft.fftfreq(8192)*rate
    expected = meta['expected_offset_hz']
    search = abs(hz-expected) < 15000
    local = (abs(hz-expected) > 20000) & (abs(hz-expected) < 60000)
    peak_bins = np.argmax(np.where(search, p, -1), axis=1)
    noise = np.maximum(np.median(p[:, local], axis=1), 1e-30)
    prominence = 10*np.log10(np.maximum(p[np.arange(len(p)), peak_bins], 1e-30)/noise)
    burst = noise > np.median(noise)*10
    blocks = words.reshape(-1, n)
    return dict(blocks=len(p), rms=distribution(np.sqrt(np.mean(abs(z)**2, axis=1))),
                peak_hz=distribution(hz[peak_bins]), noise_per_bin=distribution(noise),
                prominence_db=distribution(prominence),
                fraction_blocks_prominence_ge12=float(np.mean(prominence >= 12)),
                noise_burst_rule='local noise >10x window median; diagnostic only, no blocks excluded',
                noise_burst_blocks=int(np.count_nonzero(burst)), noise_burst_runs=runs(burst),
                low_nibble_nonzero_fraction=float(np.mean((words & 0x000f000f) != 0)),
                adjacent_identical_blocks=int(np.sum(np.all(blocks[1:] == blocks[:-1], axis=1))),
                time_scope='Indices refer to stored DMA blocks; missing blocks and absolute RF timing unknown.',
                endpoint_fraction=float(np.mean((a <= -2048)|(a >= 2047)|(b <= -2048)|(b >= 2047))),
                scope='All retained analysis-window blocks included; strongest peak per block, not coherent tone tracking.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('choose a new output')
    results = {}
    dependencies = {}
    for path in args.reports:
        report = json.loads(path.read_text(encoding='utf-8'))
        results[path.as_posix()] = {name: analyze(c, c['spectrum']['sample_rate_nominal_hz'])
                                    for name, c in report['captures'].items()}
        dependencies[path.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    dependencies[Path(__file__).relative_to(ROOT).as_posix()] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    out = dict(recorded_at=datetime.now().astimezone().isoformat(), status='analysis_completed',
               device_accessed=False, thresholds_changed=False, results=results, dependencies=dependencies,
               scope='Retained DMA-aligned windows only; no physical limit or new RF acceptance claim.')
    args.output.write_text(json.dumps(out, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
