"""QPSK waveform compatibility, acquisition and throughput regression checks."""
import json
from pathlib import Path
import sys
import time
import subprocess
import tempfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comm_protocol import QPSKReceiver, prbs15, stream, FRAME_SYMBOLS, SPS, symbols, rrc, PREAMBLE, HEADER_SYMBOLS


def reference_prbs(seq, count):
    state = (seq % 32767) + 1
    out = []
    for _ in range(count):
        out.append(state & 1)
        state = (state >> 1) | (((state ^ (state >> 1)) & 1) << 14)
    return np.array(out, np.uint8)


def feed_chunks(receiver, z):
    at = 0
    sizes = (511, 8192, 17001, 73, 16384)
    while at < len(z):
        size = sizes[(at // 73) % len(sizes)]
        receiver.feed(z[at:at+size])
        at += size


def verify():
    # Exercise the actual bounded-memory file writer across its chunk boundary.
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp)/'qpsk.fc32'
        samples = 132*FRAME_SYMBOLS*SPS
        subprocess.run([sys.executable, '-B', 'tools/comm_waveform.py',
                        '--modulation', 'qpsk', '--seconds', str(samples/1920000),
                        '--output', str(path)], check=True, capture_output=True)
        written = np.fromfile(path, np.complex64)
        expected, _ = stream(132)
        assert np.allclose(written, .25*expected[:samples], atol=2e-8)
        r = QPSKReceiver()
        feed_chunks(r, written[126*FRAME_SYMBOLS*SPS:])
        assert r.frames >= 5 and r.last_seq == 130 and r.sequence_missing == 0, r.summary()
        meta = json.loads(path.with_suffix('.json').read_text())
        assert meta['sequence_repeats'] is False
        # Missing/legacy metadata must be rejected before hardware discovery.
        meta['sequence_repeats'] = True
        path.with_suffix('.json').write_text(json.dumps(meta))
        rejected = subprocess.run([sys.executable, '-B', 'tools/comm_realtime.py',
                        '--receiver', 'outputs/host/windows-realtime-candidate-v5/sdr_receive.exe', '--port', 'COM9',
                        '--frequency-hz', '2300000000', '--duration-s', '1',
                        '--modulation', 'qpsk', '--tx-file', str(path),
                        '--output', str(Path(temp)/'result.json')], capture_output=True, text=True)
        assert rejected.returncode != 0 and 'unique sequence metadata mismatch' in rejected.stderr, rejected.stderr
        # BW1 uses the same sample geometry at twice the physical rate.
        subprocess.run([sys.executable, '-B', 'tools/comm_waveform.py',
                        '--modulation', 'qpsk', '--seconds', str(samples/3840000),
                        '--sample-rate', '3840000', '--amplitude-scale', '2', '--output', str(path)],
                        check=True, capture_output=True)
        assert np.allclose(np.fromfile(path,np.complex64), .5*expected[:samples], atol=4e-8)
        meta=json.loads(path.with_suffix('.json').read_text())
        assert meta['sample_rate_hz']==3840000 and meta['symbol_rate']==480000 and meta['amplitude_scale']==2
    # Preserve every on-air PRBS value, including state/period wraparound.
    for seq, count in ((0, 2048), (1, 2048), (32766, 2048),
                       (32767, 2048), (0xffffffff, 2048), (53, 40000)):
        assert np.array_equal(prbs15(seq, count), reference_prbs(seq, count))
    rng = np.random.default_rng(8910)
    z, _ = stream(frames=40, first_seq=123)
    wide = QPSKReceiver(sample_rate=3840000)
    feed_chunks(wide, (z*np.exp(2j*np.pi*22000*np.arange(len(z))/3840000))[379:])
    ws = wide.summary()
    assert ws['frames'] == 39 and ws['ber'] == 0 and abs(ws['cfo_median_hz']-22000)<10, ws
    fractional_rows=[]
    for fraction in (0,.125,.25,.375,.5,.625,.75,.875):
        at=np.arange(len(z)-1)+fraction
        y=np.interp(at,np.arange(len(z)),z.real)+1j*np.interp(at,np.arange(len(z)),z.imag)
        y*=np.exp(2j*np.pi*22000*np.arange(len(y))/3840000)
        r=QPSKReceiver(sample_rate=3840000);feed_chunks(r,y)
        fs=r.summary()
        assert fs['frames']>=39 and fs['ber']==0 and fs['evm_median_rms']<.03, fs
        fractional_rows.append(dict(fraction=fraction,evm=fs['evm_median_rms']))
    # Independent clocks walk symbol timing in both directions.
    for ratio in (.99998,1.00002):
        at=np.arange(int((len(z)-1)/ratio))*ratio
        y=np.interp(at,np.arange(len(z)),z.real)+1j*np.interp(at,np.arange(len(z)),z.imag)
        r=QPSKReceiver();feed_chunks(r,y)
        assert r.frames>=38 and r.summary()['ber']<1e-3 and r.summary()['evm_median_rms']<.04, r.summary()
    # Payload-only inversion must remain an error after preamble timing/gain fit.
    sy=np.concatenate([symbols(i) for i in range(20)]).reshape(-1,FRAME_SYMBOLS)
    sy[:,len(PREAMBLE)+HEADER_SYMBOLS:]*=-1
    pulses=np.zeros(sy.size*SPS,np.complex64);pulses[::SPS]=sy.reshape(-1)
    r=QPSKReceiver();feed_chunks(r,np.convolve(pulses,rrc()))
    assert r.frames>=19 and r.summary()['ber']>.99 and r.summary()['evm_median_rms']>1.9, r.summary()
    rows = []
    for cfo in (-9500, 6200):
        y = .3*z*np.exp(1j*(.9+2*np.pi*cfo*np.arange(len(z))/1920000))
        y += .0003*(rng.normal(size=len(z))+1j*rng.normal(size=len(z)))
        r = QPSKReceiver()
        started = time.perf_counter()
        feed_chunks(r, y[379:])
        elapsed = time.perf_counter()-started
        s = r.summary()
        assert s['frames'] == 39 and s['ber'] == 0, s
        assert s['sequence_missing'] == 0 and abs(s['cfo_median_hz']-cfo) < 10, s
        rows.append(dict(cfo_hz=cfo, seconds=elapsed,
                         signal_seconds=len(y)/1920000, frames=s['frames']))
    # A mid-frame sample loss must trigger acquisition of subsequent frames.
    at = 17*FRAME_SYMBOLS*SPS+123
    r = QPSKReceiver()
    feed_chunks(r, np.r_[z[:at], z[at+421:]])
    assert r.frames >= 37 and r.sequence_missing >= 1, r.summary()
    # Explicit host gap resets synchronization and records the discontinuity.
    r.reset()
    assert r.discontinuities == 1 and len(r.buffer) == 0
    feed_chunks(r, z)
    assert r.frames >= 77
    r = QPSKReceiver()
    feed_chunks(r, (rng.normal(size=200000)+1j*rng.normal(size=200000)).astype(np.complex64))
    assert r.frames == 0 and r.summary()['ber'] is None
    return dict(status='passed', device_accessed=False,
                checks=['fractional_timing_all_sample_phases', 'bidirectional20ppm_clock_drift', 'payload_inversion_visible_after_preamble_fit', 'BW1_sample_rate_and_CFO', 'file_writer_overlap_add_and_unique_sequence', 'legacy_waveform_rejected_before_hardware', 'PRBS_air_compatibility', 'arbitrary_start_and_chunks',
                        'CFO_and_noise', 'sample_loss_reacquisition',
                        'explicit_gap_reset', 'noise_negative_control'], timing=rows, fractional_timing=fractional_rows,
                timing_scope='Host-only diagnostic; not a live communication acceptance.')


if __name__ == '__main__':
    report = verify()
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report))
