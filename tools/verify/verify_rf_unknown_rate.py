"""Independent known-rate controls for normalized RF reference inference."""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from rf_unknown_rate import assess


def main():
    data=ROOT/'work/unknown-rate-test';data.mkdir(exist_ok=True)
    rng=np.random.default_rng(20261027);n=192000;rows=[]
    for rate in (1920000,30720000,61440000):
        captures={};t=np.arange(n)/rate
        phase=np.repeat(rng.uniform(-np.pi,np.pi,n//2000),2000)
        for name,tone in [('off',None),('tone150',157500),('rx-plus100',57500),('tone350',357500)]:
            z=300*np.exp(2j*np.pi*700000*t+1j*phase)+rng.normal(0,2,n)+1j*rng.normal(0,2,n)
            if tone is not None:z+=100*np.exp(2j*np.pi*tone*t+1j*phase)
            path=data/f'{rate}-{name}.raw'
            (np.column_stack((np.round(z.real),-np.round(z.imag))).astype('<i2')*16).tofile(path)
            captures[name]=dict(raw_path=str(path))
        result=assess(captures)
        assert result['reference_identified'],result
        assert abs(result['sample_rate_from_two_tone_spacing_hz']/rate-1)<.001,result
        assert abs(result['retune_shift_hz']-100000)<1000,result
        missing=dict(captures,off=captures['tone150']);assert not assess(missing)['reference_identified']
        wrong=dict(captures,**{'rx-plus100':captures['tone150']});assert not assess(wrong)['reference_identified']
        rows.append(dict(input_rate_hz=rate,estimated_rate_hz=result['sample_rate_from_two_tone_spacing_hz'],
                         retune_shift_hz=result['retune_shift_hz']))
    paths=[Path(__file__),ROOT/'tools/rf_unknown_rate.py',ROOT/'tools/sdr/amplitude.py',ROOT/'tools/sdr/artifacts.py']
    report=dict(status='passed',device_accessed=False,rows=rows,preexisting_tone_rejected=True,wrong_retune_rejected=True,
        scope='Independent synthetic rates, stronger unrelated carrier and block phase discontinuities; no hardware clock calibration.',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (ROOT/'records/rf/selector6-unknown-rate-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
