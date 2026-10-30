"""Versioned, RRC-shaped QPSK test frames and incremental receiver.

No USB framing. Sequence/PRBS exist only in the over-the-air waveform.
"""
import numpy as np

SPS = 8
PAYLOAD_BITS = 2048
PREAMBLE_SYMBOLS = 128
HEADER_SYMBOLS = 32
FRAME_SYMBOLS = PREAMBLE_SYMBOLS + HEADER_SYMBOLS + PAYLOAD_BITS // 2
VERSION = 'qpsk-rrc-prbs15-v1'

def map_qpsk(b):
    b = np.asarray(b, dtype=np.int8)
    return ((1-2*b[0::2]) + 1j*(1-2*b[1::2])) / np.sqrt(2)

def hard_bits(z):
    b = np.empty(2*len(z), np.uint8)
    b[0::2] = z.real < 0
    b[1::2] = z.imag < 0
    return b

def _prbs_period():
    # All nonzero states belong to the same PRBS15 cycle. Build the inverse
    # state map once, rather than executing 2048 Python iterations per frame.
    bits = np.empty(32767, np.uint8)
    positions = np.empty(32768, np.int32)
    state = 1
    for i in range(32767):
        positions[state] = i
        bits[i] = state & 1
        state = (state >> 1) | (((state ^ (state >> 1)) & 1) << 14)
    assert state == 1
    return np.tile(bits, 2), positions


_PRBS_BITS, _PRBS_POSITIONS = _prbs_period()


def prbs15(seq, count=PAYLOAD_BITS):
    start = int(_PRBS_POSITIONS[(int(seq) % 32767) + 1])
    if count <= 32767:
        return _PRBS_BITS[start:start+count].copy()
    return _PRBS_BITS[:32767].take(np.arange(start, start+count), mode='wrap')

_rng = np.random.default_rng(0x8910)
PREAMBLE = map_qpsk(_rng.integers(0,2,PREAMBLE_SYMBOLS)).repeat(1)
PREAMBLE = np.tile(PREAMBLE, 2).astype(np.complex64)

def rrc(sps=SPS, beta=.25, span=10):
    t = np.arange(-span*sps//2, span*sps//2+1) / sps
    h = np.empty_like(t)
    for i,x in enumerate(t):
        if abs(x)<1e-10: h[i] = 1 + beta*(4/np.pi-1)
        elif abs(abs(x)-1/(4*beta))<1e-10:
            h[i] = beta/np.sqrt(2)*((1+2/np.pi)*np.sin(np.pi/(4*beta)) + (1-2/np.pi)*np.cos(np.pi/(4*beta)))
        else: h[i] = (np.sin(np.pi*x*(1-beta)) + 4*beta*x*np.cos(np.pi*x*(1+beta))) / (np.pi*x*(1-(4*beta*x)**2))
    return h / np.linalg.norm(h)

def symbols(seq):
    value = int(seq) & 0xffffffff
    header = np.unpackbits(np.frombuffer(value.to_bytes(4,'big') + (value ^ 0xffffffff).to_bytes(4,'big'),np.uint8))
    return np.r_[PREAMBLE, map_qpsk(header), map_qpsk(prbs15(value))]

def stream(frames=8, sps=SPS, first_seq=0):
    sy = np.concatenate([symbols(first_seq+i) for i in range(frames)])
    u = np.zeros(len(sy)*sps,np.complex64); u[::sps]=sy
    z = np.convolve(u,rrc(sps)).astype(np.complex64)
    return z, [prbs15(first_seq+i) for i in range(frames)]

class QPSKReceiver:
    """Persistent matched filter, differential preamble search and per-frame CFO.

    Reports BER only for validated sequence/complement headers. Unknown source
    losses are not inferred from USB short reads or waveform amplitude.
    """
    def __init__(self, sample_rate=1920000, sps=SPS):
        self.fs=sample_rate; self.sps=sps; self.h=rrc(sps).astype(np.float32)
        self.dref=PREAMBLE[1:]*PREAMBLE[:-1].conj()
        self.phase_center=np.arange(len(PREAMBLE))-(len(PREAMBLE)-1)/2
        self.phase_denominator=np.dot(self.phase_center,self.phase_center)
        self.frame_indices=np.arange(FRAME_SYMBOLS)
        self.tail=np.zeros(len(self.h)-1,np.complex64)
        self.buffer=np.empty(0,np.complex64); self.last_seq=None
        self.frames=0; self.frame_errors=0; self.bit_errors=0; self.bits=0
        self.header_errors=0; self.discontinuities=0; self.sequence_missing=0
        self.locked=False
        self.cf=[];self.ev=[];self.scores=[];self.samples=0
        self.timing_offsets=[]
        self.last_rejected_header=None

    def _preamble_cost(self, start):
        sy=self.buffer[start:start+len(PREAMBLE)*self.sps:self.sps]
        phase=np.unwrap(np.angle(sy*PREAMBLE.conj()))
        slope=np.dot(self.phase_center,phase)/self.phase_denominator
        offset=np.mean(phase)-slope*(len(PREAMBLE)-1)/2
        corrected=sy*np.exp(-1j*(offset+slope*np.arange(len(PREAMBLE))))
        gain=np.vdot(PREAMBLE,corrected)/len(PREAMBLE)
        if abs(gain)<1e-10:return float('inf')
        return float(np.mean(abs(corrected/gain-PREAMBLE)**2))

    def _timed_symbols(self, start, needed):
        # Fit timing to known preamble only. No header or payload truth is
        # used for timing/equalization; their errors remain independently visible.
        sy=self.buffer[start:start+needed:self.sps]
        fraction=0.
        if start>0:
            left,center,right=(self._preamble_cost(start+d) for d in (-1,0,1))
            curvature=left-2*center+right
            if np.isfinite(curvature) and curvature>1e-12:
                fraction=float(np.clip((left-right)/(2*curvature),-1.,1.))
                step=1 if fraction>=0 else -1
                adjacent=self.buffer[start+step:start+step+needed:self.sps]
                sy=sy+abs(fraction)*(adjacent-sy)
        return sy,fraction
    def reset(self):
        self.buffer=np.empty(0,np.complex64);self.tail[:]=0
        self.last_seq=None;self.discontinuities+=1
        self.locked=False
    def feed(self,z):
        z=np.asarray(z,np.complex64); self.samples+=len(z)
        joined=np.r_[self.tail,z]
        filtered=np.convolve(joined,self.h,mode='valid')
        self.tail=joined[-(len(self.h)-1):].copy()
        self.buffer=np.r_[self.buffer,filtered]
        events=[];sps=self.sps;needed=FRAME_SYMBOLS*sps
        pre=PREAMBLE; dref=self.dref
        while len(self.buffer)>=needed:
            best=None;candidates=[]
            # Search only positions with a full frame retained; suffix is kept
            # for next arbitrary input chunk, rather than reusing old payload.
            search_samples=len(self.buffer)-needed+1
            # After a validated frame, its successor starts at the retained
            # boundary (allow a few symbols for sample-clock drift). Avoid
            # correlating the entire queued suffix again for every frame.
            # A failed prediction immediately falls back to full acquisition.
            if self.locked:search_samples=min(search_samples,4*sps)
            for off in range(sps):
                count=max(0,(search_samples-1-off)//sps+1)
                if not count:continue
                sy=self.buffer[off:off+(count+len(dref))*sps:sps]
                d=sy[1:]*sy[:-1].conj()
                d=d/np.maximum(np.abs(d),1e-12)
                corr=np.abs(np.correlate(d,dref,mode='valid')[:count])/len(dref)
                if not len(corr):continue
                hits=np.flatnonzero(corr>=.72)
                if len(hits):
                    i=int(hits[0]);candidates.append((float(corr[i]),off+i*sps))
            if candidates:
                first=min(c[1] for c in candidates)
                best=max((c for c in candidates if c[1]<first+sps),key=lambda c:c[0])
            if best is None or best[0]<.72:
                if self.locked:
                    self.locked=False;continue
                self.buffer=self.buffer[search_samples:];break
            score,start=best
            sy,timing_fraction=self._timed_symbols(start,needed)
            phase=np.unwrap(np.angle(sy[:len(pre)]*pre.conj()))
            slope=np.dot(self.phase_center,phase)/self.phase_denominator
            offset=np.mean(phase)-slope*(len(pre)-1)/2
            correction=np.exp(-1j*(offset+slope*self.frame_indices))
            corrected=sy*correction
            gain=np.vdot(pre,corrected[:len(pre)])/len(pre)
            if abs(gain)<1e-10:
                self.buffer=self.buffer[start+sps:];continue
            corrected/=gain
            hb=hard_bits(corrected[len(pre):len(pre)+HEADER_SYMBOLS])
            hh=np.packbits(hb).tobytes();seq=int.from_bytes(hh[:4],'big');check=int.from_bytes(hh[4:],'big')
            if seq ^ check != 0xffffffff:
                self.last_rejected_header=dict(sequence=seq,complement=check,
                    cfo_hz=float(slope*self.fs/(2*np.pi*sps)),preamble_score=score,
                    timing_fractional_sample=timing_fraction,
                    rx_sample_index=self.samples-len(self.buffer)+start)
                self.header_errors+=1;self.locked=False;self.buffer=self.buffer[start+sps:];continue
            payload=corrected[len(pre)+HEADER_SYMBOLS:]
            expected=prbs15(seq);received=hard_bits(payload)
            errors=int(np.count_nonzero(expected!=received))
            reference=map_qpsk(expected)
            evm=float(np.sqrt(np.mean(abs(payload-reference)**2)))
            cfo=float(slope*self.fs/(2*np.pi*sps))
            if self.last_seq is not None:
                delta=(seq-self.last_seq)&0xffffffff
                if 1<delta<100000:self.sequence_missing+=delta-1
            self.last_seq=seq;self.frames+=1;self.bits+=len(expected)
            self.locked=True
            self.bit_errors+=errors;self.frame_errors+=bool(errors)
            for values,value in ((self.cf,cfo),(self.ev,evm),(self.scores,score)):
                values.append(value)
                if len(values)>1000:del values[:len(values)-1000]
            self.timing_offsets.append(timing_fraction)
            if len(self.timing_offsets)>1000:del self.timing_offsets[:-1000]
            events.append(dict(sequence=seq,bit_errors=errors,bits=len(expected),evm_rms=evm,cfo_hz=cfo,preamble_score=score,
                timing_fractional_sample=timing_fraction,
                rx_sample_index=self.samples-len(self.buffer)+start))
            # Retain one matched-filter sample for negative fractional timing.
            self.buffer=self.buffer[start+needed-1:]
        return events
    def summary(self):
        return dict(frames=self.frames,sample_rate_hz=self.fs,header_errors=self.header_errors,bits_compared=self.bits,
            bit_errors=self.bit_errors,ber=self.bit_errors/self.bits if self.bits else None,
            decoded_frame_error_rate=self.frame_errors/self.frames if self.frames else None,
            sequence_missing=self.sequence_missing,discontinuities=self.discontinuities,
            cfo_median_hz=float(np.median(self.cf)) if self.cf else None,
            evm_median_rms=float(np.median(self.ev)) if self.ev else None,
            timing_fractional_sample_median=float(np.median(self.timing_offsets)) if self.timing_offsets else None,
            last_rejected_header=self.last_rejected_header,
            buffered_samples=len(self.buffer),total_lost_samples=None,
            metric_scope='BER on validated headers; decoded-frame FER excludes missed headers. Sequence gaps do not identify USB loss location. CFO/EVM recent1000 frames.')

def demod(samples,sps=SPS):
    r=QPSKReceiver(sps=sps);r.feed(samples);return r.summary()
