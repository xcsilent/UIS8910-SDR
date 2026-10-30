"""Synthetic relative-response power, edge and drift checks; no hardware."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from rf_response import power,summarize,experimental_power


def main():
    directory=ROOT/'work/rf-response-test';directory.mkdir(exist_ok=True)
    rate=1920000;t=np.arange(int(rate*.4))/rate
    rng=np.random.default_rng(501)
    observations=[]
    for amplitude in (100,100/np.sqrt(2)):
        z=amplitude*np.exp(2j*np.pi*152500*t)+rng.normal(0,1,len(t))+1j*rng.normal(0,1,len(t))
        raw=np.column_stack((np.round(z.real),-np.round(z.imag))).astype('<i2')*16
        path=directory/('amplitude'+str(len(observations))+'.raw');raw.tofile(path)
        observations.append(power(path,150000,rate))
    assert all(r['tone_identified'] and r['low_nibble_nonzero_fraction']==0 for r in observations)
    measured=10*np.log10(observations[1]['noise_subtracted_power']/observations[0]['noise_subtracted_power'])
    assert abs(measured+3.0103)<.05,measured
    # A deliberately imperfect independent rate estimate must still locate a
    # wide-offset tone and preserve its relative power; it is not a clock claim.
    rate=30720000;estimate=30763191.634;n=192000;t=np.arange(n)/rate
    wide=[]
    for amplitude in (100,100/np.sqrt(2)):
        z=amplitude*np.exp(2j*np.pi*7007500*t)+rng.normal(0,1,n)+1j*rng.normal(0,1,n)
        path=directory/('experimental'+str(len(wide))+'.raw')
        (np.column_stack((np.round(z.real),-np.round(z.imag))).astype('<i2')*16).tofile(path)
        wide.append(experimental_power(path,7000000,estimate))
    assert all(v['tone_identified'] and v['sample_rate_hz'] is None for v in wide)
    assert abs(10*np.log10(wide[1]['noise_subtracted_power']/wide[0]['noise_subtracted_power'])+3.0103)<.1
    # Lossy2048-sample DMA blocks need independent windows: phase jumps must
    # not change the relative half-power measurement at wide offsets.
    blocked=[];dma=2048;n=np.arange(dma)/rate
    phases=rng.uniform(-np.pi,np.pi,(128,1))
    for index,amplitude in enumerate((100,100/np.sqrt(2))):
        z=amplitude*np.exp(2j*np.pi*9000000*n+1j*phases)
        z+=rng.normal(0,1,z.shape)+1j*rng.normal(0,1,z.shape)
        path=directory/('blocked'+str(index)+'.raw')
        (np.column_stack((np.round(z.real.ravel()),-np.round(z.imag.ravel()))).astype('<i2')*16).tofile(path)
        blocked.append(power(path,9000000,rate,dma_samples=dma))
    assert all(v['tone_identified'] and v['analysis_dma_samples']==dma for v in blocked)
    blocked_db=10*np.log10(blocked[1]['noise_subtracted_power']/blocked[0]['noise_subtracted_power'])
    assert abs(blocked_db+3.0103)<.1,blocked_db
    points=[dict(offset_hz=offset,spectrum=dict(tone_identified=True,noise_subtracted_power=10**(level/10)))
        for offset,level in ((150000,0),(-150000,0),(-450000,-2),(-500000,-3.5),
            (450000,-1),(550000,-2.5),(600000,-4),(150000,.2))]
    result=summarize(copy.deepcopy(points))
    assert result['total_minus3db_width_bracket_hz']==[1000000,1100000]
    drifting=copy.deepcopy(points);drifting[-1]['spectrum']['noise_subtracted_power']=10**(.2)
    assert summarize(drifting)['total_minus3db_width_bracket_hz'] is None
    rebound=copy.deepcopy(points);rebound.insert(-1,dict(offset_hz=650000,
        spectrum=dict(tone_identified=True,noise_subtracted_power=10**(-.1))))
    assert summarize(rebound)['relative_minus3db_edges']['positive']['nonmonotonic_after_crossing']
    assert summarize(rebound)['total_minus3db_width_bracket_hz'] is None
    missing=copy.deepcopy(points);missing[0]['spectrum']['tone_identified']=False
    try:summarize(missing)
    except ValueError:pass
    else:raise AssertionError('missing reference accepted')
    report=dict(status='passed',device_accessed=False,hardware_tested=False,
        known_half_power_db=float(measured),edge_bracket_checked=True,
        independent_phase_2048_sample_half_power_db=float(blocked_db),
        reference_drift_and_rebound_rejected=True,missing_reference_rejected=True,
        dependencies={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
            for name in ('tools/verify/verify_rf_response.py','tools/rf_response.py','tools/rf_reference.py','tools/rf_unknown_rate.py','tools/sdr/amplitude.py','tools/sdr/sample_rate.py','firmware/sdr_receiver/sample_rate.h')})
    (ROOT/'records/rf/bw01-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
