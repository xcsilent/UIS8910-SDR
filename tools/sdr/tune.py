"""One-process native stop/drain/config/start timing, metadata only in Python."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
from .rf_catalog import ROOT,plan_receive
from .sample_rate import nominal_rate


def validate_program(program):
    """Reject stale timing executables or a substituted companion DLL pre-I/O."""
    manifest=program.parent/'tune-build.json'
    build=json.loads(manifest.read_text(encoding='utf-8'))
    expected=next(a['sha256'] for a in build['artifacts'] if (ROOT/a['path']).resolve()==program)
    def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
    if build['status']!='built' or sha(program)!=expected:
        raise ValueError('timing executable differs from tune-build.json; rebuild it')
    for path in (ROOT/'host/windows/tune_benchmark.c',ROOT/'firmware/sdr_receiver/sample_rate.h',program.parent/'sdr_usb.dll'):
        key=path.relative_to(ROOT).as_posix()
        if build['dependencies'].get(key)!=sha(path):
            raise ValueError('timing source/rate table or companion DLL differs from tune build: '+key)
    return manifest


def benchmark(args, *, executable=None):
    if os.name!='nt':raise ValueError('run the native timing consumer on Windows')
    for band,hz in ((args.band,args.frequency_hz),(args.second_band,args.second_frequency_hz)):
        plan_receive(band,frequency_hz=hz,gain_index=40)
    if not 1<=args.rounds<=8:raise ValueError('rounds must be1..8')
    if args.bandwidth_index not in range(6):raise ValueError('bandwidth must be0..5')
    request_bytes=getattr(args,'request_bytes',65536)
    if not 512<=request_bytes<=4*1024*1024 or request_bytes%512:
        raise ValueError('request bytes must be512-byte multiples up to4MiB')
    if not args.port.startswith('COM') or not args.port[3:].isdigit():raise ValueError('expected COM port')
    output=Path(args.output).resolve()
    if output.exists() or not output.parent.is_dir():raise ValueError('choose a new report in an existing directory')
    executable=executable or getattr(args,'receiver_executable',None)
    program=Path(executable).resolve() if executable else ROOT/'outputs/host/tune/sdr_tune_benchmark.exe'
    if not program.exists():raise ValueError('build tools/build_tune_benchmark.py with WSL first')
    manifest=validate_program(program)
    command=[str(program),args.port,str(args.band),str(args.frequency_hz),str(args.second_band),
        str(args.second_frequency_hz),str(args.bandwidth_index),str(args.rounds),str(request_bytes)]
    report=dict(status='starting',recorded_at=datetime.now().astimezone().isoformat(),
        device_accessed=True,command=command,reference_transmitter_used=False,
        firmware_changed=False,chip_reset=False,
        scope='host delivery timing of unchanged stop/drain/config/start API using reused native handles; not exact RF/sample-clock interruption or tuning-only hardware settling')
    with output.open('x',encoding='utf-8') as stream:
        try:
            result=subprocess.run(command,capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
            report.update(exit_code=result.returncode,stderr=result.stderr)
            native=json.loads(result.stdout)
            report['native']=native
            if (native.get('bandwidth_index')!=args.bandwidth_index or native.get('request_bytes')!=request_bytes or
                native.get('nominal_sample_rate_hz')!=nominal_rate(args.bandwidth_index)):
                raise RuntimeError('native timing configuration does not match requested mode/read size')
            if native['status']!='passed' or result.returncode:
                raise RuntimeError('native timing consumer failed; retain terminal results')
            sessions=native['sessions']
            if len(sessions)!=args.rounds*2 or any(not s['device_drained'] or s['error'] for s in sessions):
                raise RuntimeError('missing successful drained sessions')
            def describe(values):
                return dict(count=len(values),minimum=min(values),median=statistics.median(values),maximum=max(values))
            report['timing_ms']=dict(
                first_launch_call_to_delivery=sessions[0]['call_to_first_delivery_ms'],
                restart_call_to_first_delivery=describe([s['call_to_first_delivery_ms'] for s in sessions[1:]]),
                stop_request_to_drained_return=describe([s['stop_to_return_ms'] for s in sessions]),
                previous_last_delivery_to_next_first=describe([s['previous_delivery_gap_ms'] for s in sessions[1:]]))
            # Identity is checked by the native session API before each START.
            # This benchmark never infers a gap from nominal sample counts.
            report['status']='passed'
        except Exception as error:
            report.update(status='failed',error=str(error))
        paths=[ROOT/p for p in (
            'host/windows/tune_benchmark.c','tools/sdr/tune.py',
            )]+[program,program.parent/'sdr_usb.dll',manifest]
        report['dependencies']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        report['finished_at']=datetime.now().astimezone().isoformat()
        json.dump(report,stream,indent=2);stream.write('\n')
    return report
