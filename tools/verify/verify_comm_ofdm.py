"""Framed OFDM acquisition, independent payload metrics and live-speed checks."""
import json
import hashlib
from pathlib import Path
import sys
import time
import subprocess
import tempfile
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comm_ofdm_realtime import OFDMReceiver, stream, FRAME_SAMPLES, FS, STEP


def chunks(receiver, z):
    at = 0
    for n in iter(lambda: (73, 8192, 511, 17001)[(at//73) % 4], None):
        if at >= len(z):break
        receiver.feed(z[at:at+n])
        at += n
    # The live runner captures a post-TX tail. Model that here so a finite
    # synthetic source also drains the causal channel filter and timing margin.
    receiver.feed(np.zeros(64,np.complex64))


def verify():
    # File generator amplitude affects TX samples, not modulation/PRBS identity.
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'ofdm.fc32'
        args=[sys.executable,'-B','tools/comm_waveform.py','--modulation','ofdm',
              '--seconds',str(3*FRAME_SAMPLES/FS),'--output',str(path)]
        subprocess.run(args+['--amplitude-scale','1.5'],check=True,capture_output=True)
        written=np.fromfile(path,np.complex64)
        assert np.allclose(written,1.5*stream(3),atol=1e-7)
        r=OFDMReceiver();chunks(r,written)
        assert r.frames==3 and r.summary()['ber']==0, r.summary()
        rejected=subprocess.run(args+['--amplitude-scale','10'],capture_output=True,text=True)
        assert rejected.returncode!=0 and 'full scale' in rejected.stderr
        assert not path.with_suffix('.json').exists(), 'Overrange source retains valid metadata'
    rng = np.random.default_rng(8910)
    z = stream(80, first_seq=901)
    rows = []
    # BW1 doubles physical sample rate and CFO range, not FFT sample geometry.
    y = z*np.exp(2j*np.pi*22000*np.arange(len(z))/3840000)
    wide = OFDMReceiver(sample_rate=3840000)
    chunks(wide, y[379:])
    ws = wide.summary()
    assert ws['frames'] == 79 and ws['ber'] == 0 and abs(ws['cfo_median_hz']-22000)<20, ws
    rows.append(dict(sample_rate_hz=3840000, cfo_hz=22000, summary=ws))
    for cfo, channel, start in ((0, [1], 0), (-11500, [1], 379),
                                (9300, [1, 0, .27j, 0, 0, -.16], 1231)):
        y = np.convolve(z, channel)[:len(z)]
        y *= .3*np.exp(1j*(.7+2*np.pi*cfo*np.arange(len(y))/FS))
        y += .0002*(rng.normal(size=len(y))+1j*rng.normal(size=len(y)))
        r = OFDMReceiver()
        begin = time.perf_counter()
        chunks(r, y[start:])
        elapsed = time.perf_counter()-begin
        s = r.summary()
        assert s['frames'] >= (80 if start == 0 else 79), s
        assert s['ber'] == 0 and s['evm_median_rms'] < .03, s
        assert abs(s['cfo_median_hz']-cfo) < 20, s
        rows.append(dict(cfo_hz=cfo, multipath_taps=channel.__len__(),
                         start=start, seconds=elapsed, signal_seconds=len(y)/FS, summary=s))
    # A carrier outside the96 occupied bins can cancel the short-preamble
    # autocorrelation at lag64 without destroying the OFDM data. Acquisition
    # must tolerate that condition without loosening payload quality metrics.
    t=np.arange(len(z))/FS
    interfered=(z+.04*np.exp(2j*np.pi*615000*t))*np.exp(-2j*np.pi*3000*t)
    r=OFDMReceiver();chunks(r,interfered)
    assert r.frames>=79 and r.summary()['ber']==0 and r.summary()['evm_median_rms']<.03,r.summary()
    rows.append(dict(scenario='out_of_occupied_bins_carrier',summary=r.summary()))
    from comm_ofdm_realtime import CHANNEL_FILTER
    # Preserve the occupied edge plus tested CFO, reject the observed BW0
    # out-of-band carrier, and keep arbitrary chunking equivalent to one feed.
    n=np.arange(len(CHANNEL_FILTER))
    response=lambda f:abs(np.sum(CHANNEL_FILTER*np.exp(-2j*np.pi*f*n)))
    assert response(.1953)>.98 and response(.32)<.005
    all_filter=OFDMReceiver();chunk_filter=OFDMReceiver()
    expected_filter=all_filter._condition(interfered)
    conditioned=[]
    for at in range(0,len(interfered),511):conditioned.append(chunk_filter._condition(interfered[at:at+511]))
    assert np.allclose(np.concatenate(conditioned),expected_filter,atol=2e-7,rtol=1e-6)
    whole=OFDMReceiver();whole.feed(interfered);whole.feed(np.zeros(64,np.complex64))
    assert whole.frames>=79 and whole.summary()['ber']==0,whole.summary()
    # Match the live receiver's pre-TX idle: a new DC step has a finite
    # settling interval and is not promised lossless on the first frame.
    from comm_ofdm_realtime import DC_WINDOW
    y=np.r_[np.full(2*DC_WINDOW,.025-.025j),
            z*np.exp(-2j*np.pi*2500*np.arange(len(z))/FS)+(.025-.025j)]
    dc=OFDMReceiver();chunks(dc,y)
    assert dc.frames>=79 and dc.summary()['ber']==0 and dc.summary()['evm_median_rms']<.05,dc.summary()
    rows.append(dict(scenario='receiver_DC_offset',summary=dc.summary()))
    at = 27*FRAME_SAMPLES+935
    r = OFDMReceiver()
    chunks(r, np.r_[z[:at], z[at+421:]])
    assert r.frames >= 77 and r.sequence_missing >= 1, r.summary()
    # Do not fit unknown data to its own reference: payload-only attenuation
    # must remain visible in EVM even when training/header/pilots decode.
    changed=z.copy().reshape(-1,FRAME_SAMPLES)
    changed[:,4*STEP:]*=.5
    r=OFDMReceiver();chunks(r,changed.reshape(-1))
    assert r.frames==80 and .49<r.summary()['evm_median_rms']<.51, r.summary()
    # Pilots distinguish common phase rotation from payload-only errors.
    changed=z.copy().reshape(-1,FRAME_SAMPLES)
    changed[:,4*STEP:]*=-1
    r=OFDMReceiver();chunks(r,changed.reshape(-1))
    # Pilots invert as well: this is common phase, legitimately corrected.
    assert r.frames==80 and r.summary()['ber']==0, r.summary()
    from comm_ofdm_realtime import FFT, CP, BINS, IS_PILOT
    changed=z.copy().reshape(-1,FRAME_SAMPLES)
    for row in changed:
        symbols=row[4*STEP:].reshape(-1,STEP)
        freq=np.fft.fft(symbols[:,CP:],axis=1)
        freq[:,BINS[~IS_PILOT]%FFT]*=-1
        u=np.fft.ifft(freq,axis=1)
        symbols[:,:CP]=u[:,-CP:];symbols[:,CP:]=u
    r=OFDMReceiver();chunks(r,changed.reshape(-1))
    assert r.frames==80 and r.summary()['ber']>.99 and r.summary()['evm_median_rms']>1.9, r.summary()
    # An unrelated unframed OFDM signal must not produce payload metrics.
    from comm_ofdm import make
    old, _, _ = make(frames=200)
    for negative in (old, (rng.normal(size=200000)+1j*rng.normal(size=200000))*.05):
        r = OFDMReceiver();chunks(r, negative)
        assert r.frames == 0 and r.summary()['ber'] is None, r.summary()
    from comm_ofdm_realtime import PREAMBLE
    for negative in (.05*np.exp(2j*np.pi*120000*np.arange(200000)/FS),
                     np.tile(PREAMBLE,600)*.08):
        r=OFDMReceiver();chunks(r,negative)
        assert r.frames==0 and r.summary()['ber'] is None,r.summary()
    # Slow independent sample-clock drift must be tracked by pilots and
    # reacquisition rather than assuming identical TX/RX time bases.
    positions=np.arange(int(len(z)/1.00002))*1.00002
    y=np.interp(positions,np.arange(len(z)),z.real)+1j*np.interp(positions,np.arange(len(z)),z.imag)
    r=OFDMReceiver();chunks(r,y)
    assert r.frames>=77 and r.summary()['ber']<1e-3, r.summary()
    r = OFDMReceiver();chunks(r, z[:10*FRAME_SAMPLES+1000]);r.reset()
    chunks(r, z[13*FRAME_SAMPLES+400:])
    assert r.discontinuities == 1 and r.frames >= 75, r.summary()
    return dict(status='passed', device_accessed=False,
        checks=['file_amplitude_preserves_payload_and_rejects_overrange', 'BW1_sample_rate_and_CFO', 'arbitrary_start_chunks', 'CFO_11500Hz', 'independent_training_multipath',
                'out_of_occupied_bins_carrier_acquisition','receiver_DC_offset','channel_filter_pass_stop_and_chunking','carrier_and_preamble_only_negative',
                'sample_loss_reacquisition', 'host_gap_reset', 'legacy_and_noise_negative',
                'payload_attenuation_visible_in_EVM', 'payload_inversion_detected',
                'pilot_common_phase_tracking', '20ppm_sample_clock_drift'], rows=rows,
        scope='Host synthetic checks; no physical RF or live USB acceptance.',
        dependencies={p.as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (Path(__file__).relative_to(Path.cwd()),Path('tools/comm_ofdm_realtime.py'),Path('tools/comm_protocol.py'),Path('tools/comm_waveform.py'))})


if __name__ == '__main__':
    report = verify()
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report))
