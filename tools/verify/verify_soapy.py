"""Windows SoapySDR numeric queue test and optional real-device lifecycle test.

Build with tools/build_soapy.py first. --hardware explicitly opens the module;
it does not transmit or flash. Stop/drain before changing configurations.
"""
from pathlib import Path
import argparse
from datetime import datetime
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hardware', action='store_true')
    parser.add_argument('--port', default='COM9')
    parser.add_argument('--sample-rate',type=int,choices=(1920000,3840000,7680000,15360000,30720000),default=3840000)
    parser.add_argument('--bw-mode',type=int,choices=range(6),help='explicit mode, notably BW5 at30.72Msps; must match sample rate')
    parser.add_argument('--auto-route',action='store_true',help='test B5 to B40 active Auto retune')
    parser.add_argument('--auto-b3-lower',action='store_true',help='test active Auto1375 to1447MHz and repeat capture')
    parser.add_argument('--auto-high-boundary',action='store_true',help='test B40 to B3 overlap guard with active stream')
    parser.add_argument('--output', type=Path, default=ROOT / 'work/soapy-verification.json')
    parser.add_argument('--area', type=Path, default=ROOT / 'outputs/host/soapy')
    parser.add_argument('--queue-test', type=Path, default=ROOT / 'work/soapy-uis8910/queue-test.exe')
    args = parser.parse_args()
    if args.bw_mode is not None and args.sample_rate!=(1920000,3840000,7680000,15360000,30720000,30720000)[args.bw_mode]:
        parser.error('explicit BW mode and sample rate must match')
    area = args.area.resolve()
    queue_test = args.queue_test.resolve()
    if not area.is_relative_to(ROOT/'outputs/host') or not queue_test.is_relative_to(ROOT/'work'):
        parser.error('area and queue test must reside in project output/work directories')
    env = dict(os.environ)
    env['PATH'] = str(area) + os.pathsep + env.get('PATH', '')
    env['SOAPY_SDR_PLUGIN_PATH'] = str(area)

    def run(command):
        p = subprocess.run(list(map(str, command)), env=env, capture_output=True, text=True, timeout=90)
        if p.returncode:
            raise RuntimeError(str(command) + '\n' + p.stdout + p.stderr)
        return dict(stdout=p.stdout, stderr=p.stderr, exit_code=p.returncode)

    report = dict(status='passed', recorded_at=datetime.now().astimezone().isoformat(),
                  device_accessed=args.hardware, hardware_tested=args.hardware,
                  requested_sample_rate=args.sample_rate,requested_bw_mode=args.bw_mode,
                  scope='numeric conversion/queue; optional Soapy lifecycle, not new RF range or timestamp evidence')
    report['queue'] = run([queue_test])
    report['capabilities'] = json.loads(run([area/'soapy_receive_probe.exe','--capabilities'])['stdout'])
    if args.hardware:
        report['info'] = json.loads(run([sys.executable, '-B', ROOT / 'tools/debug/uis_debug.py',
            '--port', args.port, '--timeout', '5', 'info'])['stdout'])
        address = 'driver=uis8910,port=' + args.port
        report['enumeration'] = run([area / 'SoapySDRUtil.exe', '--find=' + address])
        report['official_probe'] = run([area / 'SoapySDRUtil.exe', '--probe=' + address])
        report['captures'] = []
        for numeric_format in ['CF32', 'CS16']:
            mode = 'auto-b3-lower' if args.auto_b3_lower else ('auto-high' if args.auto_high_boundary else ('auto' if args.auto_route else 'manual'))
            command=[area / 'soapy_receive_probe.exe', args.port, numeric_format,args.sample_rate,mode]
            if args.bw_mode is not None:command.append(args.bw_mode)
            observation = run(command)
            result = json.loads(observation['stdout'])
            if result['status'] != 'passed' or not result['read_pairs'] or not result['active_retune']:
                raise RuntimeError('No valid Soapy capture/retune')
            for terminal in [result['last_session'], result['repeat_session']]:
                if terminal['native_error'] or terminal['device_drained'] != 1:
                    raise RuntimeError('Soapy session did not drain cleanly')
                if args.auto_route and (not terminal['auto_route'] or terminal['applied_band']!=40 or terminal['frequency_hz']!=2000000000):
                    raise RuntimeError('Auto target did not apply')
                if args.auto_high_boundary and (not terminal['auto_route'] or terminal['applied_band']!=3 or terminal['frequency_hz']!=1885000000):
                    raise RuntimeError('Auto overlap guard did not apply')
                if args.auto_b3_lower and (not terminal['auto_route'] or terminal['applied_band']!=3 or terminal['frequency_hz']!=1447000000):
                    raise RuntimeError('Auto B3 lower target did not apply')
            if args.bw_mode is not None and result['last_session']['bandwidth_index']!=args.bw_mode:
                raise RuntimeError('explicit mode not present in terminal hardware session')
            if result['repeat_session']['bandwidth_index']!=0:
                raise RuntimeError('repeat session did not return to BW0')
            observation['result'] = result
            report['captures'].append(observation)
    paths = [Path(__file__), area / 'build.json', queue_test]
    build = json.loads((area / 'build.json').read_text())
    paths += [ROOT / row['path'] for row in build['artifacts']]
    report['dependencies'] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
