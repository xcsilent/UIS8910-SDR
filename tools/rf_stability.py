"""Offline tone frequency versus retained sample position; never accesses hardware."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import numpy as np
from sdr.sample_rate import nominal_rate
from sdr.artifacts import recorded_file

ROOT = Path(__file__).resolve().parents[1]


def track(z, rate, expected, windows=32, dma_samples=2000):
    """Average aligned DMA-sized windows, avoiding phase continuity assumptions."""
    if dma_samples not in (2000,2048):
        raise ValueError('supported DMA window sizes are2000 or2048 complex samples')
    size = dma_samples
    stride = size * windows
    taper = np.hanning(size)
    frequency = np.fft.fftfreq(32768) * rate
    search = abs(frequency - expected) < 15000
    rows = []
    for start in range(0, len(z) - stride + 1, stride):
        blocks = z[start:start + stride].reshape(windows, size).copy()
        blocks -= blocks.mean(axis=1)[:, None]
        power = np.mean(abs(np.fft.fft(blocks * taper, n=32768, axis=1)) ** 2, axis=0)
        peak = int(np.argmax(np.where(search, power, -1)))
        left, center, right = np.log(np.maximum(power[[(peak-1) % len(power), peak, (peak+1) % len(power)]], 1e-30))
        denominator = left - 2 * center + right
        shift = float(.5 * (left-right) / denominator) if denominator < 0 else 0.
        shift = max(-.5, min(.5, shift))
        rows.append(dict(retained_sample_start=start, retained_sample_count=stride,
                         peak_hz=float(frequency[peak] + shift * rate / len(power))))
    if not rows:
        raise ValueError('not enough samples for one complete averaging group')
    peaks = [r['peak_hz'] for r in rows]
    return dict(groups=rows, min_hz=min(peaks), max_hz=max(peaks),
                span_hz=max(peaks)-min(peaks), median_hz=float(np.median(peaks)))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--reference-record', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists() or not args.output.resolve().is_relative_to(ROOT):
        raise ValueError('choose a new output within the project')
    reference = json.loads(args.reference_record.read_text(encoding='utf8'))
    dma_bytes=reference.get('analysis_dma_block_bytes',8000)
    if dma_bytes not in (8000,8192):raise ValueError('unsupported reference DMA geometry')
    rate = nominal_rate(reference['bandwidth_index'])
    captures = {}
    dependencies = [Path(__file__), args.reference_record, ROOT/'tools/sdr/artifacts.py', ROOT/'tools/sdr/sample_rate.py', ROOT/'firmware/sdr_receiver/sample_rate.h']
    for label in ('tone150', 'rx-plus100', 'tone350'):
        capture = reference['captures'][label]
        metadata = recorded_file(capture['record'])
        saved = json.loads(metadata.read_text(encoding='utf8'))
        if not saved['transport_completed']:
            raise ValueError('incomplete transport')
        path = recorded_file(capture['raw_path'])
        words = np.fromfile(path, dtype='<u4')
        x = (words & 65535).astype('<u2').view('<i2').astype(float) / 16
        y = (words >> 16).astype('<u2').view('<i2').astype(float) / 16
        result = track(x - 1j*y, rate, capture['spectrum']['expected_offset_hz'],dma_samples=dma_bytes//4)
        result.update(raw_path=str(path), file_bytes=path.stat().st_size,
                      capture_started_at=saved['started_at'], capture_finished_at=saved['finished_at'],
                      observed_gap_ms=saved['observed_gap_ms'], epoch=capture['epoch'])
        captures[label] = result
        dependencies.append(metadata)
    output = dict(status='offline_frequency_stability_observed', recorded_at=datetime.now().astimezone().isoformat(),
                  device_accessed=False, payload_hashed=False, sample_rate_nominal_hz=rate,
                  analysis_dma_block_bytes=dma_bytes,
                  method=f'32 aligned {dma_bytes//4}-sample Hann powers averaged per group; 32768 zero padding and log-parabolic peak interpolation. Padding does not improve physical resolution.',
                  captures=captures,
                  median_retune_shift_hz=captures['tone150']['median_hz']-captures['rx-plus100']['median_hz'],
                  median_tone_separation_hz=captures['tone350']['median_hz']-captures['tone150']['median_hz'],
                  scope='Retained sample order, not uniform wall time. Raw gaps have unknown positions. Tone estimator is not calibrated clock/PLL diagnosis and does not override original RF acceptance.',
                  dependencies={p.resolve().relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies})
    args.output.write_text(json.dumps(output, indent=2)+'\n', encoding='utf8')
    print(json.dumps({k: {a:v[a] for a in ('min_hz','max_hz','span_hz','median_hz')} for k,v in captures.items()}, indent=2))


if __name__ == '__main__':
    main()
