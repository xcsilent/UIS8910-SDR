"""Single entry point for current SDR status and offline planning.

Does not replay historical experiment runners or reset a receiver.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help='show the last recorded firmware/session, without hardware access')
    commands.add_parser('rf-catalog', help='all native RF rows, implemented software envelopes and calibration evidence; offline')
    rf_snapshot = commands.add_parser('rf-snapshot', help='read-only runtime RF NV/table snapshot; requires an already stopped/drained receiver')
    rf_snapshot.add_argument('--port', required=True)
    rf_snapshot.add_argument('--output', type=Path, required=True)
    rf_status=commands.add_parser('rf-status',help='read matching opt-in RF phase diagnostic after STOP/drain; never configures or starts RF')
    rf_status.add_argument('--port',required=True)
    rf_status.add_argument('--cp-build',type=Path,required=True)
    rf_status.add_argument('--output',type=Path,required=True)
    execution=commands.add_parser('rf-execution',help='offline ABI5 phase deltas and last RF-local command pointer classification; no device access')
    execution.add_argument('--trace',type=Path,required=True)
    execution.add_argument('--output',type=Path,required=True)
    pre_status=commands.add_parser('rx-pre-status',help='read stopped experimental CP PRE capture-state export')
    pre_status.add_argument('--port',required=True)
    pre_status.add_argument('--cp-build',type=Path,required=True)
    pre_status.add_argument('--selector',type=int,choices=(5,6,7),required=True)
    pre_status.add_argument('--output',type=Path,required=True)
    frontend=commands.add_parser('rf-frontend',help='read-only full runtime RF frontend NV; already stopped/drained receiver required')
    frontend.add_argument('--port',required=True)
    frontend.add_argument('--output',type=Path,required=True)
    fem=commands.add_parser('fem-override',help='experimental next-capture B5/B8 switch value; configure only after successful stop/drain')
    fem.add_argument('--port',required=True)
    fem.add_argument('--value',choices=('default','2','5'),help='omit to query; requires advertised operation53/ABI1')
    fem.add_argument('--output',type=Path,required=True)
    tune = commands.add_parser('tune-benchmark', help='host-observed stop/drain/config/start timing; no RF transmitter or firmware change')
    tune.add_argument('--port', required=True)
    tune.add_argument('--band', type=int, default=5)
    tune.add_argument('--frequency-hz', type=int, default=881500000)
    tune.add_argument('--second-band', type=int, default=5)
    tune.add_argument('--second-frequency-hz', type=int, default=881600000)
    tune.add_argument('--bandwidth-index', type=int, choices=(0,1,2,3,4,5), default=0)
    tune.add_argument('--request-bytes',type=int,default=65536)
    tune.add_argument('--receiver-executable',type=Path,help='matched sdr_tune_benchmark.exe and DLL build')
    tune.add_argument('--rounds', type=int, default=3)
    tune.add_argument('--output', type=Path, required=True)
    plan = commands.add_parser('plan', help='offline current BW0 configuration, without deploying')
    plan.add_argument('--band', type=int, required=True)
    plan.add_argument('--frequency-hz', type=int, required=True)
    plan.add_argument('--gain-index', type=int, default=40)
    receive = commands.add_parser('receive', help='native finite SDR capture with separate JSON metadata')
    receive.add_argument('--port',required=True)
    receive.add_argument('--band',type=lambda v:0 if v.lower()=='auto' else int(v),default=0,help='auto(default) or manual raw route ID')
    receive.add_argument('--frequency-hz',type=int,default=881500000)
    receive.add_argument('--gain-index',type=int,default=40)
    receive.add_argument('--bandwidth-index',type=int,choices=(0,1,2,3,4,5),default=0)
    receive.add_argument('--receiver-executable',type=Path,help='explicit matched candidate CLI; default remains the installed host baseline')
    receive.add_argument('--unrestricted-frequency',action='store_true',help='manual RF route without band envelope; requires matching candidate CLI/DLL')
    receive.add_argument('--milliseconds',type=int,default=1000)
    receive.add_argument('--requests',type=int,default=32)
    receive.add_argument('--request-bytes',type=int,default=65536)
    receive.add_argument('--file-queue-blocks',type=int,default=32)
    receive.add_argument('--sync-file',action='store_true')
    receive.add_argument('--iq-output',type=Path)
    receive.add_argument('--output',type=Path,required=True)
    probe = commands.add_parser('usb-probe', help='read current USB speed and endpoint descriptors')
    probe.add_argument('--output', type=Path, required=True)
    bench = commands.add_parser('usb-benchmark', help='finite raw USB benchmark after manual candidate flash')
    bench.add_argument('--port', required=True)
    bench.add_argument('--source',choices=('fixed','bw0'),default='fixed')
    bench.add_argument('--band',type=int,default=5)
    bench.add_argument('--frequency-hz',type=int)
    bench.add_argument('--gain-index',type=int)
    bench.add_argument('--milliseconds', type=int, default=10000)
    bench.add_argument('--block-bytes', type=int, default=16384)
    bench.add_argument('--slots', type=int, default=8)
    bench.add_argument('--requests', type=int, default=8)
    bench.add_argument('--request-bytes', type=int, default=65536)
    bench.add_argument('--raw-io', action='store_true')
    bench.add_argument('--iq-output', type=Path, help='new raw file; omit for memory-only benchmark')
    bench.add_argument('--sync-file', action='store_true')
    bench.add_argument('--file-queue-blocks', type=int, default=32)
    bench.add_argument('--output', type=Path, required=True)
    bench.add_argument('--experimental-pre-selector',type=int,choices=(5,6,7),help='finite matching CP PRE experiment; sample rate unknown')
    schedule = commands.add_parser('scheduler', help='query separate AP scheduler counters; configure only before capture or after drain')
    schedule.add_argument('--port',required=True)
    schedule.add_argument('--wait-us',type=int)
    schedule.add_argument('--burst-us',type=int)
    schedule.add_argument('--auto',action='store_true',help='restore bandwidth-dependent defaults; requires scheduler policy ABI2')
    schedule.add_argument('--output',type=Path,required=True)
    segments = commands.add_parser('segments',help='query USB segment elapsed statistics; enable/disable only while stopped')
    segments.add_argument('--port',required=True)
    segments.add_argument('--enabled',type=int,choices=(0,1))
    segments.add_argument('--queue',action='store_true',help='read versioned queue supply counters; no configuration change')
    segments.add_argument('--refill',action='store_true',help='read bounded AP-observed refill timelines; requires advertised refill ABI1')
    segments.add_argument('--output',type=Path,required=True)
    scratch = commands.add_parser('scratch-drops',help='read stopped experimental scratch complete-pair loss counter')
    scratch.add_argument('--port',required=True)
    scratch.add_argument('--output',type=Path,required=True)
    verify = commands.add_parser('verify', help='verify saved project evidence and current document links')
    verify.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'status':
        state = json.loads((ROOT/'docs/project-state.json').read_text(encoding='utf-8'))
        value = dict(as_of=state['as_of'], live_device_query=False,
                     installed_firmware=state['installed_firmware'],
                     last_recorded_session=state['hardware_evidence']['current_receiver_session'],
                     task=state['current_task_plan'], raw_usb=state.get('sdr_delivery'))
    elif args.command == 'rf-execution':
        from sdr.rf_execution import analyze
        try:value=analyze(args)
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    elif args.command == 'scratch-drops':
        from sdr.scratch_drops import read
        value=read(args)
        print(json.dumps(value,ensure_ascii=False,indent=2))
        return 0 if value['status']=='passed' else 1
    elif args.command == 'rf-catalog':
        from sdr.rf_catalog import catalog
        value=catalog()
    elif args.command == 'rx-pre-status':
        from sdr.rx_pre_status import snapshot
        value=snapshot(args.port,args.cp_build,args.selector,args.output)
        print(json.dumps(value,ensure_ascii=False,indent=2))
        return 0 if value['status']=='passed' else 1
    elif args.command == 'rf-status':
        from sdr.rf_status import snapshot
        value=snapshot(args.port,args.cp_build,args.output)
        print(json.dumps(value,ensure_ascii=False,indent=2));return 0 if value['status']=='passed' else 1
    elif args.command == 'rf-snapshot':
        from sdr.rf_runtime import snapshot
        value=snapshot(args.port, args.output)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value['status']=='passed' else 1
    elif args.command == 'rf-frontend':
        from sdr.rf_frontend import frontend
        try:value=frontend(args)
        except ValueError as error:parser.error(str(error))
        print(json.dumps(value,ensure_ascii=False,indent=2))
        return 0 if value['status']=='passed' else 1
    elif args.command == 'fem-override':
        from sdr.fem_override import configure
        try:value=configure(args)
        except ValueError as error:parser.error(str(error))
        print(json.dumps(value,ensure_ascii=False,indent=2))
        return 0 if value['status']=='passed' else 1
    elif args.command == 'segments':
        from sdr.segments import segments
        try:value=segments(args)
        except ValueError as error:parser.error(str(error))
        print(json.dumps(value,ensure_ascii=False,indent=2))
        return 0 if value['status']=='passed' else 1
    elif args.command == 'scheduler':
        from sdr.scheduler import scheduler
        try:value=scheduler(args)
        except ValueError as error:parser.error(str(error))
        print(json.dumps(value,ensure_ascii=False,indent=2))
        return 0 if value['status']=='passed' else 1
    elif args.command == 'tune-benchmark':
        from sdr.tune import benchmark
        try: value=benchmark(args)
        except ValueError as error: parser.error(str(error))
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value['status']=='passed' else 1
    elif args.command == 'plan':
        from sdr.rf_catalog import plan_receive
        try:
            value = plan_receive(args.band, frequency_hz=args.frequency_hz, gain_index=args.gain_index)
        except ValueError as error:
            parser.error(str(error))
    elif args.command == 'receive':
        from sdr.receive import receive
        try:value=receive(args)
        except ValueError as error:parser.error(str(error))
        print(json.dumps(value,ensure_ascii=False,indent=2))
        return 0 if value['status'] in ('passed','completed_with_loss','completed_with_gaps','stopped_by_user') else 1
    elif args.command == 'usb-probe':
        from sdr.usb_probe import probe
        value = probe(args.output)
    elif args.command == 'usb-benchmark':
        command = [sys.executable, '-B', str(ROOT/'tools/usb/benchmark.py'),
                   '--port', args.port, '--output', str(args.output),'--source',args.source]
        for name in ('milliseconds', 'block_bytes', 'slots', 'requests', 'request_bytes', 'file_queue_blocks'):
            command.extend(['--'+name.replace('_', '-'), str(getattr(args, name))])
        for name in ('band','frequency_hz','gain_index'):
            if getattr(args,name) is not None:
                command.extend(['--'+name.replace('_','-'),str(getattr(args,name))])
        if args.raw_io:
            command.append('--raw-io')
        if args.experimental_pre_selector is not None:
            command.extend(['--experimental-pre-selector',str(args.experimental_pre_selector)])
        if args.iq_output:
            command.extend(['--iq-output', str(args.iq_output.resolve())])
        if args.sync_file:
            command.append('--sync-file')
        return subprocess.call(command, cwd=ROOT)
    else:
        command = [sys.executable, '-B', str(ROOT/'tools/verify/check_project_state.py')]
        if args.output:
            command.extend(['--output', str(args.output)])
        return subprocess.call(command, cwd=ROOT)
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
