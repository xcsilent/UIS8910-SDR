"""Check recorded native QPC timing/accounting without accessing hardware."""
import hashlib
import json
from pathlib import Path
import statistics
import argparse
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def check_tool(directory):
    """Exercise current build identity and pre-device CLI rejection only."""
    sys.path.insert(0,str(ROOT/'tools'))
    from sdr.tune import validate_program
    from unittest.mock import patch
    program=(directory/'sdr_tune_benchmark.exe').resolve()
    manifest=validate_program(program)
    original_read=Path.read_bytes
    rejected=[]
    # Reject changed code/table/DLL without modifying any retained artifact.
    for target in (program,program.parent/'sdr_usb.dll',ROOT/'host/windows/tune_benchmark.c',
                   ROOT/'firmware/sdr_receiver/sample_rate.h'):
        def changed(path,selected=target):
            raw=original_read(path)
            return raw+b'changed' if path==selected else raw
        with patch.object(Path,'read_bytes',changed):
            try:validate_program(program)
            except ValueError:rejected.append(target.relative_to(ROOT).as_posix())
            else:raise AssertionError('stale timing dependency accepted: '+str(target))
    invalid=[]
    for bw,size in ((6,8192),(7,8192),(5,0),(5,8193),(5,4194816)):
        result=subprocess.run([str(program),'COM9','40','2000000000','40','2000100000',
                               str(bw),'1',str(size)],capture_output=True,text=True)
        assert result.returncode==2 and not result.stdout,(bw,size,result.returncode,result.stdout)
        invalid.append(dict(bandwidth_index=bw,request_bytes=size,exit_code=2))
    return dict(status='passed',device_accessed=False,hardware_tested=False,
                preflight_dependency_changes_rejected=rejected,invalid_cli_rejected_before_device_open=invalid,
                scope='Current native build and pre-I/O argument/identity gates only; valid BW0..5 timing requires hardware.',
                dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (Path(__file__),ROOT/'tools/sdr/tune.py',program,program.parent/'sdr_usb.dll',manifest)})


def check(report):
    assert report['status']=='passed' and report['exit_code']==0
    native=report['native'];rows=native['sessions'];rate=native['host_qpc_frequency']
    assert native['status']=='passed' and native['error']==0 and rate>0
    assert len(rows)==2*native['rounds'] and not native['sample_timestamps']
    previous=None
    for row in rows:
        begin,first,last,stop,end=(row[k] for k in ('begin_qpc','first_delivery_qpc','last_delivery_qpc','stop_requested_qpc','return_qpc'))
        assert 0<begin<=first<last==stop<=end
        assert row['device_drained'] and not any(row[k] for k in ('error','control_error','cleanup_error'))
        assert row['delivered_bytes']>0 and row['delivered_bytes']%4==0
        assert row['usb_bytes']==row['delivered_bytes']+row['drain_discarded_bytes']
        assert abs((first-begin)*1000/rate-row['call_to_first_delivery_ms'])<.00001
        assert abs((end-stop)*1000/rate-row['stop_to_return_ms'])<.00001
        if previous:
            assert row['epoch']>previous['epoch'] and begin>=previous['return_qpc']
            gap=(first-previous['last_delivery_qpc'])*1000/rate
            assert abs(gap-row['previous_delivery_gap_ms'])<.00001
        previous=row
    assert report['timing_ms']['previous_last_delivery_to_next_first']['median']==statistics.median(r['previous_delivery_gap_ms'] for r in rows[1:])
    return len(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool-dir',type=Path,default=ROOT/'outputs/host/tune',help='current timing build; no hardware access')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.tool_dir:
        if not args.output:parser.error('--tool-dir requires --output')
        result=check_tool(args.tool_dir)
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,indent=2));return



if __name__=='__main__':main()
