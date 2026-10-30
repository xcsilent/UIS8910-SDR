"""Check checkpoint interpretation: wrap, unstable/missing and NV row boundaries."""
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from sdr.rf_execution import classify_pointer,interpret


def main():
    source=ROOT/'records/rf/frontend-observer-v28-b5-trace.json'
    fixture=json.loads(source.read_text());decoded=interpret(fixture)
    assert decoded['all_checkpoints_usable'] and decoded['counter_changes_observed']
    assert [r['delta_modulo32'] for r in decoded['phases']]==[None,0,0,1,4]
    assert classify_pointer('0x97f0')==dict(region='switch_open',nv_row=4,entry=0,aligned=True)
    assert classify_pointer('0x9914')==dict(region='switch_open',nv_row=22,entry=1,aligned=True)
    assert classify_pointer('0x974c')['region']=='initialization'
    assert classify_pointer('0x97af')['region']=='initialization' and not classify_pointer('0x97af')['aligned']
    assert classify_pointer('0x97b0')['region']=='switch_open'
    assert classify_pointer('0xffff')['region']=='unclassified'
    mutated=copy.deepcopy(fixture)
    for entry,count in zip(mutated['execution_observations'],[0xffffffff,0,0,0,0]):
        entry.update(count_before=count,count_after=count)
    assert interpret(mutated)['phases'][1]['delta_modulo32']==1
    mutated['execution_observations'][1]['stable_double_read']=False
    result=interpret(mutated)
    assert not result['all_checkpoints_usable']
    assert result['phases'][1]['delta_modulo32'] is None and result['phases'][2]['delta_modulo32'] is None
    for change in ('abi','order','stable'):
        bad=copy.deepcopy(fixture)
        if change=='abi':bad['trace_abi']=4
        elif change=='order':bad['records'][1]['stage']='after_prepare'
        else:bad['execution_observations'][1]['count_after']+=1
        try:interpret(bad)
        except ValueError:pass
        else:raise AssertionError('inconsistent evidence accepted')
    paths=[Path(__file__),source,ROOT/'tools/sdr/rf_execution.py']
    report=dict(status='passed',device_accessed=False,tests=['live-record phase correspondence','NV region/row and alignment boundaries','counter wrap','unstable phases do not produce deltas','incompatible ABI/order/stable values rejected'],
        scope='Offline interpretation tests; source hardware evidence retained independently, no new hardware proof.',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (ROOT/'records/rf/frontend-execution-analysis-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status='passed',tests=len(report['tests']))))


if __name__=='__main__':main()
