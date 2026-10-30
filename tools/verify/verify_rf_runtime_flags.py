"""Compare retained v17 RF phase flags; observations are not live reads."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
base=ROOT/'records/rf'
prefix='reference-rf-dual-v17-'
names=[prefix+n for n in ['b5-8815-reference-tone150-rf-status.json','b5-700-reference-tone150-rf-status.json','b5-675-reference-tone150-rf-status.json']]
rows=[]
for name in names:
    report=json.loads((base/name).read_text(encoding='utf-8'))
    assert report['status']=='passed' and report['complete'] and report['generation']=='0x52630501'
    phases=report['records'];assert len(phases)==5
    rows.append({'report':(base/name).relative_to(ROOT).as_posix(),'epoch':report['epoch'],
        'phases':[{'stage':r['stage'],'b4e0':r['analog_mode_flag_b4e0'],'b52a':r['digital_flag_b52a'],
                   'route_30468':r['route_30468'],'route_30480':r['route_30480']} for r in phases]})
assert all(p['b4e0']==0 and p['b52a']==0 for r in rows for p in r['phases'])
files=[Path(__file__).resolve()]+[base/n for n in names]
out={'status':'passed','device_accessed':False,'hardware_tested':False,'observations':rows,
     'interpretation':'In these three retained v17 BW0 capture checkpoints both software flags are zero. Snapshots are not continuous; this does not prove absence of transient writes, all producer paths, hardware bit meanings, PLL lock, or that these flags cause 675 MHz weak response.',
     'dependencies':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
(base/(prefix+'runtime-flags-comparison.json')).write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':out['status'],'captures':len(rows),'phase_samples':sum(len(r['phases']) for r in rows)}))
