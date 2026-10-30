"""Offline interpretation of ABI5 checkpoints, with no hardware or NV writes."""
import hashlib
import json
from pathlib import Path

from .rf_catalog import ROOT
from .rf_status import STAGES
from .rf_frontend import MIPI


def classify_pointer(pointer):
    """Classify RF-local addresses using the verified NV copy layout only."""
    address=int(pointer,0) if isinstance(pointer,str) else pointer
    if not isinstance(address,int) or not 0<=address<=0xffffffff:
        raise ValueError('invalid RF-local pointer')
    base=0x974c
    if base<=address<base+100:
        offset=address-base
        return dict(region='initialization',entry=offset//4,aligned=offset%4==0)
    for name,nv_offset in MIPI.items():
        start=base+nv_offset-0x2ac
        if start<=address<start+24*16:
            offset=address-start
            return dict(region=name,nv_row=offset//16,entry=(offset%16)//4,aligned=offset%4==0)
    return dict(region='unclassified',aligned=address%4==0)


def interpret(trace):
    if trace.get('trace_abi')!=5 or trace.get('status')!='passed':
        raise ValueError('a passed ABI5 trace report is required')
    records=trace.get('records',[]);observations=trace.get('execution_observations',[])
    if len(records)!=len(observations) or len(records)>5:
        raise ValueError('incomplete phase correspondence')
    phases=[];previous=None
    for index,(route,entry) in enumerate(zip(records,observations),1):
        stage=STAGES[index]
        if route.get('stage')!=stage or entry.get('stage')!=stage:
            raise ValueError('trace phase order mismatch')
        matching=entry.get('matching_observer') is True
        stable=matching and entry.get('stable_double_read') is True
        count=entry.get('count_after')
        if stable and (type(count) is not int or not 0<=count<=0xffffffff or count!=entry.get('count_before') or entry.get('last_pointer_before')!=entry.get('last_pointer_after')):
            raise ValueError('inconsistent stable observation')
        phase=dict(stage=stage,selector=route.get('selector'),rx_port=route.get('rx_port'),
            matching_observer=matching,stable_double_read=stable,
            count=count if stable else None,delta_modulo32=None,counter_change_observed=None,
            last_pointer=entry.get('last_pointer_after') if stable else None,
            last_pointer_layout=classify_pointer(entry['last_pointer_after']) if stable else None)
        if previous is not None and previous['stable_double_read'] and stable:
            phase['delta_modulo32']=(count-previous['count'])&0xffffffff
            phase['counter_change_observed']=count!=previous['count']
            phase['previous_stage']=previous['stage']
        phases.append(phase);previous=phase
    usable=all(p['stable_double_read'] for p in phases) and bool(phases)
    changed=any(p['counter_change_observed'] for p in phases)
    return dict(status='passed',device_accessed=False,source_epoch=trace.get('epoch'),
        source_generation=trace.get('generation'),source_complete=trace.get('complete',False),
        phases=phases,all_checkpoints_usable=usable,
        counter_changes_observed=changed,
        next_action=('Resolve observer signature/unstable checkpoints before attributing helper execution.' if not usable else
                     'Correlate changed intervals and last pointer region with selected route; use controlled RF reference only after delivery context is established.' if changed else
                     'No counter difference observed between retained checkpoints; inspect dispatch conditions or observation visibility. Do not repeat identical zero snapshots.'),
        limitations=['Modulo delta is not exact call count if reset/reload, full counter wraps or stale cache cannot be excluded.',
                    'No difference does not prove no calls; a nonzero delta is an observed counter change, not external ACK.',
                    'Last pointer identifies only one saved argument; it does not enumerate earlier commands or prove their values.',
                    'NV row is an index, not standard LTE band; address classification does not read live NV or confirm board routing.',
                    'Stable repeated values do not prove atomicity, cache visibility, controller completion or RF reception.'])


def analyze(args):
    source=args.trace.resolve();output=args.output.resolve()
    if not source.is_relative_to(ROOT) or not output.is_relative_to(ROOT) or source==output or output.exists() or not output.parent.is_dir():
        raise ValueError('choose an existing project trace and a new project output')
    result=interpret(json.loads(source.read_text(encoding='utf-8')))
    result['source']=source.relative_to(ROOT).as_posix()
    paths=[source,Path(__file__),ROOT/'tools/sdr/rf_status.py',ROOT/'tools/sdr/rf_frontend.py']
    result['dependencies']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result
