"""Reference-tone analysis in cycles/sample without a supplied sample rate."""
from pathlib import Path
import numpy as np
from sdr.artifacts import recorded_file
from sdr.amplitude import native12_amplitude


def power(path):
    words=np.fromfile(recorded_file(path),dtype='<u4')
    count=min(len(words)//2000,96)*2000
    if count<16000:raise ValueError('at least eight complete DMA-sized windows required')
    words=words[-count:]
    a=(words&65535).astype('<u2').view('<i2').astype(float)/16
    b=(words>>16).astype('<u2').view('<i2').astype(float)/16
    z=(a-1j*b).reshape(-1,2000);z-=z.mean(axis=1)[:,None]
    p=np.mean(abs(np.fft.fft(z*np.hanning(2000),n=65536,axis=1))**2,axis=0)
    f=np.fft.fftfreq(len(p))
    return f,p,dict(analyzed_complex_samples=count,low_nibble_nonzero_fraction=float(np.mean((words&0x000f000f)!=0)),
                   endpoint_fraction=float(np.mean((a<=-2048)|(a>=2047)|(b<=-2048)|(b>=2047))),
                   iq_amplitude=native12_amplitude(a,b),sample_rate_hz=None)


def peak(f,p,off=None):
    search=(f>.0005)&(f<.49)
    if off is not None:
        search &= p>=np.maximum(off,1e-30)*10
    if not np.any(search):raise ValueError('no positive-frequency candidate with ten-dB on/off contrast')
    i=int(np.argmax(np.where(search,p,-1)))
    q=np.log(np.maximum(p[i-1:i+2],1e-30));den=q[0]-2*q[1]+q[2]
    delta=float(.5*(q[0]-q[2])/den) if den<0 else 0.
    value=float(f[i]+max(-.5,min(.5,delta))/len(p))
    local=(abs(f-value)>.001)&(abs(f-value)<.005)
    return dict(peak_cycles_per_sample=value,peak_to_local_median_db=float(10*np.log10(max(p[i],1e-30)/max(float(np.median(p[local])),1e-30))))


def spectrum(path):
    f,p,metadata=power(path)
    return dict(**metadata,**peak(f,p),physical_frequency_hz=None,
                scope='Positive normalized-frequency peak only; no RF identification until reference comparison')


def assess(captures):
    spectra={name:power(c['raw_path']) for name,c in captures.items()}
    f,off,_=spectra['off'];rows={}
    try:
        for name in ('tone150','rx-plus100','tone350'):
            rows[name]=peak(f,spectra[name][1],off)
        on=rows['tone150']['peak_cycles_per_sample']
        delta=rows['tone350']['peak_cycles_per_sample']-on
        if delta<=0:raise ValueError('two-tone spacing is not positive; rate/alias interpretation unresolved')
        rate=200000/delta
        shifted=(on-rows['rx-plus100']['peak_cycles_per_sample'])*rate
        target=abs(f-on)<3/2000
        contrast=float(10*np.log10(max(float(spectra['tone150'][1][target].sum()),1e-30)/max(float(off[target].sum()),1e-30)))
        error=max(abs(rows[name]['peak_cycles_per_sample']*rate-expected) for name,expected in [('tone150',150000),('rx-plus100',50000),('tone350',350000)])
        accepted=contrast>=10 and abs(shifted-100000)<4000 and error<12000 and all(r['peak_to_local_median_db']>=12 for r in rows.values())
        return dict(status='reference_verified' if accepted else 'reference_not_identified',reference_identified=bool(accepted),
            normalized_peaks=rows,tone150_vs_off_db=contrast,retune_shift_hz=shifted,tone_separation_hz=200000,
            sample_rate_from_two_tone_spacing_hz=rate if accepted else None,candidate_sample_rate_hz=rate,
            sample_rate_nominal_hz=None,sample_rate_calibrated=False,spectral_resolution_cycles_per_sample=1/2000,
            scope='Approximate rate inferred from two finite RF tone offsets and checked by independent100kHz RX retune. No absolute clock calibration, phase continuity, unique alias proof or passband measurement.')
    except ValueError as error:
        return dict(status='reference_not_identified',reference_identified=False,error=str(error),normalized_peaks=rows,
                    sample_rate_from_two_tone_spacing_hz=None,sample_rate_nominal_hz=None)
