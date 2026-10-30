"""Compare FFT sizes on saved gapped raw IQ; never opens hardware or hashes IQ."""
import argparse,hashlib,json
from pathlib import Path
from sdr.artifacts import recorded_file
from datetime import datetime
import numpy as np
from sdr.sample_rate import nominal_rate
ROOT=Path(__file__).resolve().parents[1]

def spectra(z,rate,n):
    count=min(len(z)//n,128)
    if count<4:raise ValueError('at least four complete FFT windows required')
    blocks=z[:count*n].reshape(count,n).copy()
    blocks-=blocks.mean(axis=1)[:,None]
    window=np.hanning(n);padded=max(8192,n*4)
    power=np.mean(np.abs(np.fft.fft(blocks*window,n=padded,axis=1))**2,axis=0)/np.sum(window**2)
    return np.fft.fftfreq(padded)*rate,power,count

def compare(on,off,rate,expected,sizes):
    rows=[]
    for n in sizes:
        f,p,count=spectra(on,rate,n);_,q,_=spectra(off,rate,n)
        peak=int(np.argmax(np.where(abs(f-expected)<20000,p,-1)))
        width=0;left=right=peak
        while left>0 and p[left-1]>=p[peak]/2:left-=1
        while right+1<len(p) and p[right+1]>=p[peak]/2:right+=1
        width=(right-left+1)*rate/len(p)
        local=(abs(f-f[peak])>150000)&(abs(f-f[peak])<400000)
        target=abs(f-f[peak])<max(30000,rate/n*3)
        rows.append(dict(fft_samples=n,windows=count,bin_hz=rate/n,peak_hz=float(f[peak]),
            peak_error_hz=float(f[peak]-expected),main_peak_half_power_width_hz=width,
            hann_ideal_half_power_width_approx_hz=1.44*rate/n,
            peak_to_distant_median_db=float(10*np.log10(max(p[peak],1e-30)/max(float(np.median(p[local])),1e-30))),
            near_peak_on_off_db=float(10*np.log10(max(float(p[target].sum()),1e-30)/max(float(q[target].sum()),1e-30)))))
    return rows

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--on-record',type=Path,required=True);ap.add_argument('--off-record',type=Path,required=True)
    ap.add_argument('--expected-hz',type=float,default=150000)
    ap.add_argument('--fft-sizes',type=int,nargs='+',default=[2000,2048,8192,32768,65536])
    ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if any(n<256 or n>65536 for n in a.fft_sizes):raise ValueError('FFT size256..65536 required')
    if a.output.exists() or not a.output.resolve().is_relative_to(ROOT):raise ValueError('choose a new project output')
    reports=[json.loads(p.read_text(encoding='utf8')) for p in [a.on_record,a.off_record]]
    for key in ('band','frequency_hz','gain_index','bandwidth_index'):
        if reports[0]['config'][key]!=reports[1]['config'][key]:raise ValueError('on/off configuration differs')
    rate=nominal_rate(reports[0]['config']['bandwidth_index']);signals=[];inputs=[]
    for r in reports:
        if not r.get('transport_completed'):raise ValueError('capture transport not completed')
        path=recorded_file(r['raw_file']['path']);available=path.stat().st_size//4
        count=min(1024000,available//2000*2000)
        skip=max(0,(available-count)//2000*2000)
        words=np.fromfile(path,dtype='<u4',count=count,offset=skip*4)
        x=(words&65535).astype('<u2').view('<i2').astype(float)/16
        y=(words>>16).astype('<u2').view('<i2').astype(float)/16
        signals.append(x-1j*y);inputs.append(dict(path=str(path),file_bytes=path.stat().st_size,
            skipped_complex_samples=skip,analyzed_complex_samples=count,source_gap_ms=r.get('observed_gap_ms'),
            wall_clock_sample_positions_known=False,payload_hashed=False))
    result=dict(status='fft_observations_recorded',recorded_at=datetime.now().astimezone().isoformat(),
        device_accessed=False,sample_rate_nominal_hz=rate,inputs=inputs,
        rows=compare(*signals,rate,a.expected_hz,a.fft_sizes),
        scope='Saved IQ windows only, no live desktop/refresh proof. Large windows may span unknown source gaps; peak width is observed spectrum, not RF passband or calibrated phase noise.',
        dependencies={p.resolve().relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (Path(__file__),a.on_record,a.off_record,ROOT/'tools/sdr/sample_rate.py',ROOT/'firmware/sdr_receiver/sample_rate.h')})
    a.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(status=result['status'],rows=result['rows']),indent=2))

if __name__=='__main__':main()
