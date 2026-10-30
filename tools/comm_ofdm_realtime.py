"""Framed OFDM online receiver; RF framing never enters USB raw IQ."""
from collections import deque
import numpy as np
from comm_protocol import hard_bits, map_qpsk, prbs15

VERSION = 'ofdm-training-prbs15-v1'
FS, FFT, CP = 1920000, 256, 32
STEP = FFT+CP
BINS = np.r_[np.arange(-48, 0), np.arange(1, 49)]
PILOTS = np.array([-43, -31, -19, -7, 7, 19, 31, 43])
IS_PILOT = np.isin(BINS, PILOTS)
DATA_BINS = BINS[~IS_PILOT]
DATA_SYMBOLS = 12
PAYLOAD_BITS = DATA_SYMBOLS*len(DATA_BINS)*2
FRAME_SAMPLES = (4+DATA_SYMBOLS)*STEP
FFT_START = CP-8
FRAME_INDICES = np.arange(FRAME_SAMPLES, dtype=np.float32)
TRAIN_INDICES = (STEP+np.arange(2*STEP, dtype=np.float32))
# Select the test waveform's occupied bins before acquisition. QPSK already
# has an RRC matched filter; OFDM also needs to reject energy outside its band.
# Normalized coefficients preserve the same bin geometry at BW0 and BW1.
CHANNEL_CUTOFF = .25
_filter_indices = np.arange(33)-16
_filter = 2*CHANNEL_CUTOFF*np.sinc(2*CHANNEL_CUTOFF*_filter_indices)*np.hamming(33)
CHANNEL_FILTER = (_filter/_filter.sum()).astype(np.float32)
DC_WINDOW = 32*FFT
MAGIC = b'\x89\x10\x00\x01'
_rng = np.random.default_rng(0x0fd08910)
TRAINING = map_qpsk(_rng.integers(0, 2, 2*len(BINS)))


def time_symbol(values, bins=BINS):
    x = np.zeros(FFT, np.complex64)
    x[bins % FFT] = values
    u = (np.fft.ifft(x)*FFT/np.sqrt(len(bins))).astype(np.complex64)
    return np.r_[u[-CP:], u]


_short_bins = BINS[BINS % 4 == 0]
PREAMBLE = time_symbol(map_qpsk(_rng.integers(0, 2, 2*len(_short_bins))), _short_bins)
TRAIN = time_symbol(TRAINING)
PILOT_MATRIX = np.stack([np.where((np.arange(len(PILOTS))+i) % 2, -1., 1.)
                         for i in range(DATA_SYMBOLS+1)])
# Receiver arithmetic stays single precision; the waveform constants above
# retain their original values and therefore do not change transmitted files.
RX_TRAINING = TRAINING.astype(np.complex64)
RX_PILOT_MATRIX = PILOT_MATRIX.astype(np.float32)
RX_PILOTS = PILOTS.astype(np.float32)
RX_BINS = BINS.astype(np.float32)
PILOT_ENERGY = np.dot(RX_PILOTS, RX_PILOTS)


def pilot_values(index):
    return np.where((np.arange(len(PILOTS))+index) % 2, -1., 1.).astype(np.complex64)


def header_bits(sequence):
    v = int(sequence) & 0xffffffff
    return np.unpackbits(np.frombuffer(MAGIC+v.to_bytes(4, 'big')+
                         (v ^ 0xffffffff).to_bytes(4, 'big'), np.uint8))


def frame(sequence):
    out = [PREAMBLE, TRAIN, TRAIN]
    payload = prbs15(sequence, PAYLOAD_BITS).reshape(DATA_SYMBOLS, -1)
    for index in range(DATA_SYMBOLS+1):
        bits = (np.pad(header_bits(sequence), (0, 2*len(DATA_BINS)-96))
                if index == 0 else payload[index-1])
        v = np.empty(len(BINS), np.complex64)
        v[IS_PILOT] = pilot_values(index)
        v[~IS_PILOT] = map_qpsk(bits)
        out.append(time_symbol(v))
    return (.08*np.concatenate(out)).astype(np.complex64)


def stream(frames, first_seq=0):
    return np.concatenate([frame(first_seq+i) for i in range(frames)])


def _window_sum(x, n):
    c = np.r_[0, np.cumsum(x)]
    return c[n:]-c[:-n]


def _phasor(phase):
    # The real exponent is always zero. Real sin/cos use NumPy's vectorized
    # path without the scalar complex exponential in the per-frame hot loop.
    out = np.empty(phase.shape, np.complex64)
    out.real = np.cos(phase)
    out.imag = np.sin(phase)
    return out


class OFDMReceiver:
    def __init__(self, sample_rate=FS):
        self.fs = sample_rate
        self.buf = np.empty(0, np.complex64)
        self.frames = self.bits = self.errors = self.frame_errors = 0
        self.header_errors = self.candidates = self.sequence_missing = 0
        self.discontinuities = 0
        self.last_seq = None
        self.samples = 0
        self.evms = deque(maxlen=1000)
        self.cfos = deque(maxlen=1000)
        self.scores = deque(maxlen=1000)
        self.locked = False
        self.filter_tail = np.zeros(len(CHANNEL_FILTER)-1,np.complex64)
        self.dc_tail = np.zeros(DC_WINDOW,np.complex64)
        self.dc_sum = 0j

    def reset(self):
        self.buf = np.empty(0, np.complex64)
        self.last_seq = None
        self.locked = False
        self.discontinuities += 1
        self.filter_tail[:] = 0
        self.dc_tail[:] = 0
        self.dc_sum = 0j

    def _find(self):
        available = len(self.buf)-FRAME_SAMPLES+1
        if self.locked:
            starts = np.arange(min(33, available))
        else:
            x = self.buf[:available+STEP+64]
            a, b = x[:-64], x[64:]
            corr = _window_sum(a.conj()*b, 128)
            power = np.sqrt(_window_sum(abs(a)**2, 128)*_window_sum(abs(b)**2, 128))
            metric = abs(corr)/np.maximum(power, 1e-12)
            hits = np.flatnonzero(metric[:available] > .7)
            if not len(hits):return None
            first = int(hits[0])
            starts = np.arange(max(0, first-CP), min(available, first+STEP))
        if not len(starts):return None
        lo, hi = int(starts[0]), int(starts[-1])+STEP
        part = self.buf[lo:hi]
        # 64-sample repetition gives coarse CFO +/-fs/128.
        start = int(starts[len(starts)//2])
        u = self.buf[start:start+STEP]
        coarse = np.angle(np.vdot(u[CP:CP+192], u[CP+64:CP+256]))*self.fs/(2*np.pi*64)
        corrected = part*_phasor(np.float32(-2*np.pi*coarse/self.fs)*np.arange(len(part),dtype=np.float32))
        cor = np.correlate(corrected, PREAMBLE, 'valid')
        power = _window_sum(abs(corrected)**2, STEP)
        score = abs(cor)/np.sqrt(np.maximum(power, 1e-20)*np.vdot(PREAMBLE, PREAMBLE).real)
        at = int(np.argmax(score))
        if score[at] < .48:return None
        return lo+at, float(coarse), float(score[at])

    def _decode(self, raw, coarse):
        # Coarse-rotate training only, then rotate the full frame once using
        # the refined CFO. Single precision avoids two complex128 frame paths.
        training = raw[STEP:3*STEP]*_phasor(np.float32(-2*np.pi*coarse/self.fs)*TRAIN_INDICES)
        a = training[FFT_START:FFT_START+FFT]
        b = training[STEP+FFT_START:STEP+FFT_START+FFT]
        residual = np.angle(np.vdot(a, b))*self.fs/(2*np.pi*STEP)
        cfo = coarse+residual
        corrected = raw*_phasor(np.float32(-2*np.pi*cfo/self.fs)*FRAME_INDICES)
        freq = np.fft.fft(corrected.reshape(-1, STEP)[:, FFT_START:FFT_START+FFT], axis=1)[:, BINS % FFT]
        channel = (freq[1]+freq[2])*.5/RX_TRAINING
        if np.min(abs(channel)) < 1e-9:return None
        eq = freq[3:]/channel
        # Payload truth is never used to estimate equalization or phase.
        phase = np.unwrap(np.angle(eq[:, IS_PILOT]/RX_PILOT_MATRIX), axis=1)
        slope = np.sum(phase*RX_PILOTS, axis=1)/PILOT_ENERGY
        eq *= _phasor(-(np.mean(phase, axis=1)[:, None]+slope[:, None]*RX_BINS))
        hb = np.packbits(hard_bits(eq[0, ~IS_PILOT])[:96]).tobytes()
        if hb[:4] != MAGIC:return None
        seq = int.from_bytes(hb[4:8], 'big')
        if seq ^ int.from_bytes(hb[8:12], 'big') != 0xffffffff:return None
        received = eq[1:, ~IS_PILOT].reshape(-1)
        expected = prbs15(seq, PAYLOAD_BITS)
        errors = int(np.count_nonzero(hard_bits(received) != expected))
        evm = float(np.sqrt(np.mean(abs(received-map_qpsk(expected))**2)))
        return dict(sequence=seq, bit_errors=errors, bits=PAYLOAD_BITS,
                    evm_rms=evm, cfo_hz=float(cfo))

    def _condition(self,z):
        # A causal moving mean is independent of caller chunk size. Its zeros
        # at nonzero FFT bins preserve the nominal occupied tones. Accumulate
        # in double precision; do not use payload truth to estimate DC.
        history=np.r_[self.dc_tail,z]
        delta=z.astype(np.complex128)-history[:len(z)]
        sums=np.cumsum(delta)+self.dc_sum
        self.dc_sum=sums[-1]
        self.dc_tail=history[-DC_WINDOW:].copy()
        z=(z-sums/DC_WINDOW).astype(np.complex64)
        joined=np.r_[self.filter_tail,z]
        filtered=np.convolve(joined,CHANNEL_FILTER,mode='valid')
        self.filter_tail=joined[-(len(CHANNEL_FILTER)-1):].copy()
        return filtered

    def feed(self, z):
        z = np.asarray(z, np.complex64)
        if not len(z):return []
        self.samples += len(z)
        z=self._condition(z)
        self.buf = np.r_[self.buf, z]
        events = []
        while len(self.buf) >= FRAME_SAMPLES:
            if self.locked and len(self.buf)<FRAME_SAMPLES+16:break
            found = self._find()
            if found is None:
                if self.locked:
                    self.locked = False
                    continue
                self.buf = self.buf[len(self.buf)-FRAME_SAMPLES+1:]
                break
            at, coarse, score = found
            self.candidates += 1
            event = self._decode(self.buf[at:at+FRAME_SAMPLES], coarse)
            if event is None:
                self.header_errors += 1
                self.locked = False
                self.buf = self.buf[at+STEP:]
                continue
            seq = event['sequence']
            event['rx_sample_index']=self.samples-len(self.buf)+at
            if self.last_seq is not None:
                delta = (seq-self.last_seq) & 0xffffffff
                if 1 < delta < 100000:self.sequence_missing += delta-1
            self.last_seq = seq
            self.frames += 1
            self.bits += event['bits']
            self.errors += event['bit_errors']
            self.frame_errors += bool(event['bit_errors'])
            self.evms.append(event['evm_rms']);self.cfos.append(event['cfo_hz']);self.scores.append(score)
            self.locked = True
            # Keep a timing margin on both sides of the expected boundary so
            # sample-clock drift cannot force a progressively late FFT window.
            self.buf = self.buf[at+FRAME_SAMPLES-16:]
            events.append(event)
        return events

    def summary(self):
        return dict(protocol=VERSION, sample_rate_hz=self.fs, frames=self.frames, bits_compared=self.bits,
            bit_errors=self.errors, ber=self.errors/self.bits if self.bits else None,
            decoded_frame_error_rate=self.frame_errors/self.frames if self.frames else None,
            evm_median_rms=float(np.median(self.evms)) if self.evms else None,
            cfo_median_hz=float(np.median(self.cfos)) if self.cfos else None,
            header_errors=self.header_errors, candidates=self.candidates,
            sequence_missing=self.sequence_missing, discontinuities=self.discontinuities,
            buffered_samples=len(self.buf), total_lost_samples=None,
            reference_alignment_verified=bool(self.frames),
            host_channel_filter=dict(taps=len(CHANNEL_FILTER),cutoff_cycles_per_sample=CHANNEL_CUTOFF,
                dc_moving_mean_samples=DC_WINDOW,
                group_delay_samples=(len(CHANNEL_FILTER)-1)//2,
                scope='Host demodulator only; raw USB and optional raw IQ file unchanged. Delay included in reported sample positions; no physical RF timing claim.'),
            metric_scope='Independent per-subcarrier training; pilot-only phase tracking; PRBS selected by validated magic/sequence/complement. FER excludes missed headers; recent1000-frame EVM/CFO. Exact source loss unknown.')
