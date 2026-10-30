"""Exercise the native module in the user's real SDR++ core (loopback server).

Uses its documented-in-source server protocol for START/STOP/tune and SmGui;
no substitute core/USB. Network framing is only the test consumer after the
plugin's float stream; firmware USB remains raw. No RF transmitter is used.
"""
from pathlib import Path
import argparse
from datetime import datetime
import hashlib
import json
import socket
import struct
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',default='COM9')
    parser.add_argument('--band',type=int,choices=(5,34),default=5)
    parser.add_argument('--gain-index',type=int,default=30,help='uncalibrated RX index; default30 for overload-aware checks')
    parser.add_argument('--rapid-retune',action='store_true',help='stress coalesced tuning including out-of-range centers; both BW modes')
    parser.add_argument('--mixed-retune',action='store_true',help='interleave active gain changes with rapid tuning and verify the final delivered configuration; requires --rapid-retune')
    parser.add_argument('--auto-route',action='store_true',help='also verify active cross-route tuning using Auto; no RF reference claim')
    parser.add_argument('--auto-b3-lower',action='store_true',help='verify new B3 lower request envelope with active Auto transitions')
    parser.add_argument('--auto-high-boundary',action='store_true',help='test B3/B40 boundary and return through overlap; no RF reference claim')
    parser.add_argument('--auto-iq-output',type=Path,help='save float32 IQ after Auto reaches 1885 MHz for external-reference analysis')
    parser.add_argument('--bandwidth-indices',type=int,nargs='+',choices=(0,1,2,3,4,5),default=[0,1],help='test requested modes, including lossy wideband without a full-rate supply gate')
    parser.add_argument('--output',type=Path,default=ROOT/'work/sdrpp-verification.json')
    parser.add_argument('--runtime-dir',type=Path,default=ROOT/'work/sdrpp/runtime')
    parser.add_argument('--build-manifest',type=Path,default=ROOT/'outputs/host/sdrpp/build.json')
    args=parser.parse_args()
    if args.mixed_retune and not args.rapid_retune:parser.error('--mixed-retune requires --rapid-retune')
    runtime=args.runtime_dir.resolve();manifest=args.build_manifest.resolve()
    if not runtime.is_relative_to(ROOT/'work') or not manifest.is_relative_to(ROOT/'outputs/host'):
        parser.error('runtime and build manifest must be within project work/outputs')
    if args.output.exists() or not args.output.resolve().is_relative_to(ROOT):
        parser.error('choose a new project output record')
    build=json.loads(manifest.read_text(encoding='utf-8'))
    for item in build['artifacts']:
        source=ROOT/item['path'];name=source.name
        actual=runtime/('modules/'+name if name=='uis8910_source.dll' else name)
        if hashlib.sha256(source.read_bytes()).hexdigest()!=item['sha256'] or hashlib.sha256(actual.read_bytes()).hexdigest()!=item['sha256']:
            parser.error('runtime differs from explicit build: '+name)
    if hashlib.sha256((runtime/'sdrpp_core.dll').read_bytes()).hexdigest()!=build['target_sdrpp_core_sha256']:
        parser.error('runtime core differs from build target')
    status=runtime/'uis8910_source_status.json'
    plugin_config=runtime/'uis8910_source_config.json'
    center=2017500000 if args.band==34 else 881500000
    # SDR++ exposes center frequency only; the native source always uses the
    # shared Auto route policy.  Keep band as a legacy diagnostic seed only.
    plugin_config.write_text(json.dumps(dict(port=args.port,band=args.band,auto_route=True,frequency_hz=center,gain_index=args.gain_index,bandwidth_index=0)))
    # Bind a free port for this test instance; do not attach to another server.
    with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    report=dict(status='running',recorded_at=datetime.now().astimezone().isoformat(),device_accessed=True,
        hardware_tested=True,desktop_visual_verified=False,
        scope='native DLL in unmodified target SDR++ core server mode; no RF source/range validation')
    logpath=ROOT/'work/sdrpp/server-test.log'
    with logpath.open('w',encoding='utf-8') as log:
        process=subprocess.Popen([str(runtime/'sdrpp.exe'),'--server','--addr','127.0.0.1','--port',str(port)],
            cwd=runtime,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        connection=None
        try:
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('SDR++ terminated: '+logpath.read_text(errors='replace'))
                try:connection=socket.create_connection(('127.0.0.1',port),.5);break
                except OSError:time.sleep(.1)
            if connection is None:raise RuntimeError('SDR++ did not listen')
            connection.settimeout(12)
            def exact(n):
                data=bytearray()
                while len(data)<n:
                    block=connection.recv(n-len(data))
                    if not block:raise RuntimeError('SDR++ connection closed')
                    data.extend(block)
                return bytes(data)
            def packet():
                kind,length=struct.unpack('<II',exact(8))
                if not 8<=length<=16000000:raise RuntimeError('Invalid server packet length')
                return kind,exact(length-8)
            def command(cmd,data=b''):
                connection.sendall(struct.pack('<III',0,12+len(data),cmd)+data)
            def ui():
                command(0)
                while True:
                    kind,data=packet()
                    if kind==1 and struct.unpack_from('<I',data)[0]==0:return data[4:]
                    if kind==6:raise RuntimeError('Server UI command failed')
            def action(label,value):
                name=label.encode();item=b'\x04'+struct.pack('<H',len(name))+name
                if type(value) is bool:item+=b'\x01'+struct.pack('<?',value)
                elif type(value) is int:item+=b'\x02'+struct.pack('<i',value)
                else:
                    value=value.encode();item+=b'\x04'+struct.pack('<H',len(value))+value
                command(1,b'\x01'+item)
                while True:
                    kind,data=packet()
                    if kind==1 and struct.unpack_from('<I',data)[0]==1:return
                    if kind==6:raise RuntimeError('Server UI action failed')
            def stats():return json.loads(status.read_text(encoding='utf-8'))
            first_ui=ui()
            for label in [b'Control COM',b'Receive mode',b'Gain index',b'Wideband FFT pacing']:
                if label not in first_ui:raise RuntimeError('Native controls absent: '+str(label))
            if b'RF route' in first_ui:raise RuntimeError('Manual RF route control still exposed')
            report['auto_route_surface_verified']=True
            report['native_controls_present']=True
            action('Wideband FFT pacing',False);ui()
            if stats()['fft_pacing_enabled']:raise RuntimeError('FFT pacing disable did not persist')
            action('Wideband FFT pacing',True);ui()
            if not stats()['fft_pacing_enabled']:raise RuntimeError('FFT pacing enable did not persist')
            report['fft_pacing_control_verified']=True
            command(6,b'\x02') # Float32, no downstream 8/16-bit quantization.
            report['captures']=[]
            for bw in args.bandwidth_indices:
                action('Receive mode',bw)
                action('Gain index',args.gain_index)
                command(4,struct.pack('<d',center));command(2)
                begin=time.monotonic();pairs=packets=0;retuned=False;maximum=0.0
                while time.monotonic()-begin<5:
                    kind,data=packet()
                    if kind==6:raise RuntimeError('SDR++ server error')
                    if kind!=2:continue
                    compression,sample_type,scale=struct.unpack_from('<HHf',data)
                    if compression or sample_type!=2 or (len(data)-8)%8:raise RuntimeError('Unexpected float IQ format')
                    count=(len(data)-8)//8;pairs+=count;packets+=1
                    if count:
                        values=struct.unpack_from('<'+str(min(64,count*2))+'f',data,8)
                        maximum=max(maximum,max(map(abs,values)))
                        if not all(-1<=v<=1 for v in values):raise RuntimeError('Float IQ outside signed12 scale')
                    if not retuned and time.monotonic()-begin>2:
                        command(4,struct.pack('<d',center+100000));retuned=True
                command(3);ui() # Ordered UI reply is the barrier after synchronous STOP/drain.
                terminal=stats()
                if terminal['fft_pacing_active'] or not terminal['fft_pacing_server_bypassed']:
                    raise RuntimeError('Server must not access uninitialized desktop IQFrontEnd')
                if not pairs or terminal['error'] or terminal['device_drained']!=1 or terminal['running']:
                    raise RuntimeError('Native stream/drain failed: '+str(terminal))
                if (not terminal.get('auto_route') or terminal['band']!=terminal.get('applied_band') or
                    terminal['bandwidth_index']!=bw or terminal['frequency_hz']!=center+100000 or
                    terminal.get('applied_gain_index')!=args.gain_index):
                    raise RuntimeError('Requested configuration did not follow')
                report['captures'].append(dict(bandwidth_index=bw,read_pairs=pairs,packets=packets,
                    active_retune=retuned,maximum_observed_float=maximum,terminal=terminal))
                if args.rapid_retune:
                    command(2)
                    # Wait for real samples before stressing the active session.
                    while packet()[0]!=2:pass
                    ui();before=stats()
                    begin=time.monotonic()
                    for index in range(120):
                        # Cross invalid centers while dragging, then return to
                        # the selected route. These must not synchronously join
                        # capture/decoder threads on the server/UI thread.
                        hz=100000000 if index%10==0 else center+(index%8)*10000
                        command(4,struct.pack('<d',hz));time.sleep(.002)
                        if args.mixed_retune and index%12==0:action('Gain index',20+index%30)
                    final_gain=37 if args.mixed_retune else args.gain_index
                    if args.mixed_retune:action('Gain index',final_gain)
                    final=center+200000
                    command(4,struct.pack('<d',final));ui()
                    barrier_ms=(time.monotonic()-begin)*1000
                    deadline=time.monotonic()+8;post_pairs=0
                    while time.monotonic()<deadline:
                        kind,data=packet()
                        if kind==6:raise RuntimeError('SDR++ rapid tuning server error')
                        if kind==2:post_pairs+=(len(data)-8)//8
                        ui();current=stats()
                        if current['error']:raise RuntimeError('Rapid tuning receive failed: '+str(current))
                        if current.get('applied_frequency_hz')==final and current.get('tune_allowed') and post_pairs>8192:
                            break
                    else:raise RuntimeError('Final rapid frequency request lost: '+str(current))
                    command(3);ui();terminal=stats()
                    if terminal['error'] or not terminal['device_drained'] or terminal['running']:
                        raise RuntimeError('Rapid retune did not stop/drain: '+str(terminal))
                    if terminal.get('applied_frequency_hz')!=final:raise RuntimeError('Final center not applied')
                    if args.mixed_retune and (terminal.get('applied_gain_index')!=final_gain or
                            terminal.get('applied_bandwidth_index')!=bw or
                            terminal.get('applied_revision')!=terminal.get('requested_revision')):
                        raise RuntimeError('Final mixed configuration not delivered: '+str(terminal))
                    if terminal['completed_sessions']>8:raise RuntimeError('Burst was not coalesced: '+str(terminal))
                    report.setdefault('rapid_retunes',[]).append(dict(bandwidth_index=bw,
                        requests=121,includes_invalid_centers=True,UI_barrier_ms=barrier_ms,
                        post_burst_pairs=post_pairs,before=before,terminal=terminal))
                    report['rapid_retunes'][-1]['interleaved_gain_requests']=11 if args.mixed_retune else 0
                    command(2)
                    while packet()[0]!=2:pass
                    begin=time.monotonic();command(4,struct.pack('<d',100000000));ui()
                    invalid_barrier_ms=(time.monotonic()-begin)*1000
                    # Remain outside the route long enough to exercise the
                    # worker's idle wait, then STOP while it is waiting.
                    deadline=time.monotonic()+5
                    while True:
                        ui();invalid=stats()
                        if not invalid.get('tune_allowed',True) and invalid['device_drained']:break
                        if time.monotonic()>deadline:raise RuntimeError('Invalid request did not drain asynchronously')
                        time.sleep(.05)
                    begin=time.monotonic();command(3);ui();stopped=stats()
                    if stopped['running'] or stopped['error'] or not stopped['device_drained']:
                        raise RuntimeError('STOP while invalid-center worker waits failed')
                    report.setdefault('invalid_center_stops',[]).append(dict(bandwidth_index=bw,
                        UI_barrier_ms=invalid_barrier_ms,stop_barrier_ms=(time.monotonic()-begin)*1000,
                        waiting=invalid,terminal=stopped))
                    command(4,struct.pack('<d',final));ui()
            if args.auto_route or args.auto_high_boundary or args.auto_b3_lower:
                # Auto is the only SDR++ route surface.  A center-frequency
                # request is sufficient to select the internal route.
                command(2)
                report['auto_route_captures']=[]
                route_points = [(881500000,5),(917500000,5),(920000000,8),
                                (917500000,8),(915000000,5),(942500000,8),(1842500000,3),
                                (2000000000,40),(2600000000,40),(881500000,5)]
                if args.auto_high_boundary:
                    route_points = [(1919900000,3),(1920000100,40),(1919900000,40),
                                    (1890000100,40),(1890000000,3),(1885000000,3)]
                if args.auto_b3_lower:
                    route_points=[(1375000000,3),(1400000000,3),(1447000000,3),
                                  (1600000000,3),(1842500000,3),(942500000,8),
                                  (1375000000,3),(2000000000,40),(1500000000,3)]
                for hz,band in route_points:
                    begin=time.monotonic();command(4,struct.pack('<d',hz));ui()
                    deadline=begin+10;post_pairs=0
                    while time.monotonic()<deadline:
                        kind,data=packet()
                        if kind==6:raise RuntimeError('Auto-route server error')
                        if kind==2:post_pairs+=(len(data)-8)//8
                        ui();current=stats()
                        if current['error']:raise RuntimeError('Auto-route failed: '+str(current))
                        if (current.get('applied_frequency_hz')==hz and current.get('applied_band')==band
                                and current.get('auto_route') and post_pairs>8192):break
                    else:raise RuntimeError('Auto-route target not reached: '+str(current))
                    report['auto_route_captures'].append(dict(frequency_hz=hz,band=band,
                        first_observed_seconds=time.monotonic()-begin,terminal=current))
                    if args.auto_iq_output and hz==1885000000:
                        # Read additional packets only after the requested session
                        # is observed; ignore any packet consumed before that point.
                        sample_bytes=bytearray()
                        while len(sample_bytes)<262144*8:
                            kind,data=packet()
                            if kind==6:raise RuntimeError('Auto IQ server error')
                            if kind==2:
                                compression,sample_type,_=struct.unpack_from('<HHf',data)
                                if compression or sample_type!=2:raise RuntimeError('Unexpected auto IQ format')
                                sample_bytes.extend(data[8:])
                        args.auto_iq_output.parent.mkdir(parents=True,exist_ok=True)
                        args.auto_iq_output.write_bytes(sample_bytes[:262144*8])
                        report['auto_iq_output']=str(args.auto_iq_output)
                command(3);ui();terminal=stats()
                if terminal['error'] or not terminal['device_drained'] or terminal['running']:
                    raise RuntimeError('Auto-route STOP/drain failed: '+str(terminal))
                report['auto_route_terminal']=terminal
            report['status']='passed'
        except Exception as error:
            report['status']='failed'
            report['error']=str(error)
        finally:
            if connection:
                try:connection.sendall(struct.pack('<III',0,12,3))
                except OSError:pass
                # On an assertion/timeout, do not tear down the server while
                # its receiver still owns USB requests. STOP is asynchronous;
                # allow the worker to drain before closing the test process.
                deadline=time.monotonic()+10
                while process.poll() is None and time.monotonic()<deadline:
                    try:
                        terminal=json.loads(status.read_text(encoding='utf-8'))
                        if not terminal.get('running',True) and terminal.get('device_drained'):
                            break
                    except (OSError,ValueError):
                        pass
                    time.sleep(.05)
                try:
                    terminal=json.loads(status.read_text(encoding='utf-8'))
                    report['cleanup_terminal']=terminal
                    report['cleanup_drained']=bool(not terminal.get('running',True)
                                                   and terminal.get('device_drained'))
                except (OSError,ValueError) as error:
                    report['cleanup_drained']=False
                    report['cleanup_error']=str(error)
                connection.close()
            # The SDR++ server loop has no exit command. STOP/drain is checked
            # above; process termination only tears down the isolated test app.
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
    dependencies=[Path(__file__),manifest,runtime/'modules/uis8910_source.dll',
        runtime/'sdr_usb.dll',runtime/'sdrpp_core.dll',runtime/'sdrpp.exe']
    report['dependencies']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies}
    report['core_log']=logpath.relative_to(ROOT).as_posix()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
    if report['status']!='passed':
        sys.exit(1)


if __name__=='__main__':main()
