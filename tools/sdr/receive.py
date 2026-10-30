"""Daily native SDR capture and separate JSON metadata; IQ stays in C/WinUSB."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
from .rf_catalog import ROOT,plan_receive,software_profiles
from .sample_rate import nominal_rate


def verify_experimental_receiver(program,floor,unrestricted=False):
    """Check executable/DLL build identity before any device operation."""
    build=json.loads(program.with_name('build.json').read_text(encoding='utf-8'))
    if build.get('experimental_b3_min_hz')!=floor:
        raise ValueError('experimental B3 host manifest floor differs')
    if bool(build.get('unrestricted_frequency'))!=unrestricted:
        raise ValueError('host unrestricted frequency setting differs')
    artifacts={str((ROOT/row['path']).resolve()):row for row in build['artifacts']}
    for path in (program,program.with_name('sdr_usb.dll')):
        row=artifacts.get(str(path.resolve()))
        if row is None or path.stat().st_size!=row['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('experimental B3 receiver artifact differs: '+str(path))

def validate(args):
    floor=getattr(args,'experimental_b3_min_hz',None)
    unrestricted=getattr(args,'unrestricted_frequency',False)
    if args.band:
        plan_receive(args.band,frequency_hz=args.frequency_hz,gain_index=args.gain_index,experimental_b3_min_hz=floor,unrestricted_frequency=unrestricted)
    elif floor is not None or unrestricted:
        raise ValueError('B3 experiment requires an explicit route, not Auto')
    elif (not 0<=args.gain_index<=124 or args.frequency_hz%100 or not any(
            p['minimum_hz']<=args.frequency_hz<=p['maximum_hz']
            for b,p in software_profiles().items() if b in (5,8,3,40))):
        raise ValueError('Auto center outside candidate software envelopes or invalid gain/grid')
    if not re.fullmatch(r'COM[0-9]{1,29}',args.port):
        raise ValueError('port must be COM followed by digits')
    if not (args.milliseconds==0 or 100<=args.milliseconds<=60000) or args.bandwidth_index not in (0,1,2,3,4,5):
        raise ValueError('capture requires0(until STOP) or100..60000 ms and BW0..BW5; device INFO must advertise the requested mode')
    if not 1<=args.requests<=32 or not 512<=args.request_bytes<=4*1024*1024 or args.request_bytes%512:
        raise ValueError('USB requests must be1..32 and512-byte multiples up to4 MiB')
    if not 2<=args.file_queue_blocks<=256 or args.file_queue_blocks*args.request_bytes>256*1024*1024:
        raise ValueError('file queue must have2..256 blocks and at most256 MiB')
    output=args.output.resolve()
    if output.exists() or not output.parent.is_dir():
        raise ValueError('choose a new JSON report in an existing directory')
    if args.iq_output is not None:
        raw=args.iq_output.resolve()
        if raw==output or raw.exists() or not raw.parent.is_dir():
            raise ValueError('choose a separate new raw file in an existing directory')

def summarize(report,raw_path=None):
    """Only metadata/counters; never open IQ payload for reading or hashing."""
    h=report['host'];w=h.get('device_status',[]);r=h.get('recovery_status',[])
    current=(len(w)==48 and len(r)==24 and w[:2]==[0x31574353,1] and r[:2]==[0x31524353,1]
        and h.get('epoch',0)>0 and w[5]==r[2]==h['epoch'])
    config=report['config']
    if config.get('requested_band',config['band'])==0 and h.get('auto_route') and h.get('band') in (5,8,3,40):
        config['requested_band']=0;config['band']=h['band'];config['auto_route']=True
    current=current and (w[8:12]==[2,nominal_rate(config['bandwidth_index']),4,12] and
        w[40]>>8==config['band'] and (w[40]>>4)&7==config['bandwidth_index'] and
        w[45]==config['gain_index'] and w[47]==config['frequency_hz'])
    device=(w[22]+(w[23]<<32)) if current else None
    received=h['bytes'];difference=device-received if device is not None else None
    report['byte_accounting']=dict(device_completed_bytes=device,host_consumed_bytes=received,
        device_minus_host_bytes=difference,lost_sample_positions_known=False,
        host_shortfall_observed=(difference>0) if difference is not None else None,
        shortfall_cause='unknown' if difference is not None and difference>0 else None)
    continuous=report['config']['duration_ms']==0
    reached=current and not continuous and w[46]>=report['config']['duration_ms']
    stopped=current and continuous and bool(h.get('stop_requested')) and not r[21]
    report['continuous_mode']=continuous
    interrupted=current and bool(r[4] or r[5] or r[7])
    drained=current and h.get('device_drained',False) and w[3]==4 and not w[4] and w[30] and w[32]==30 and w[37] and w[34]==w[35] and not r[7]
    report['requested_duration_reached']=bool(reached)
    report['source_interrupted']=bool(interrupted)
    # Independent flags keep simultaneous transport shortfall, file drops
    # and capture gaps visible even when the primary status selects gaps.
    report['file_or_consumer_loss_observed']=bool(
        h.get('file_dropped_bytes',0) or h.get('discarded_after_consumer_stop',0))
    report['observed_gap_ms']=(r[8]+(r[9]<<32)) if current else None
    report['lost_samples_known']=False
    steady=h.get('steady_device_bytes_per_second')
    measured=(current and bool(h.get('steady_device_rate_measured')) and not h.get('steady_device_counter_invalid',False)
        and h.get('steady_device_samples',0)>=3 and h.get('steady_device_window_ms',0)>=1000
        and (continuous or h.get('steady_device_window_ms',0)<=max(0,config['duration_ms']-750))
        and isinstance(steady,(int,float)) and steady>=0)
    nominal=nominal_rate(config['bandwidth_index'])*4
    report['steady_throughput_measured']=bool(measured)
    report['steady_device_bytes_per_second']=steady if measured else None
    report['supply_rate_fraction_of_nominal']=steady/nominal if measured else None
    # Supply assessment is independent of transport success and allows limited loss.
    report['supply_assessment_minimum_fraction']=0.95
    report['sustained_source_supply_verified']=False
    report['external_rf_reception_verified']=False
    report['zero_loss_required']=False
    errors=any(h.get(k,0) for k in ('win32_error','file_error','session_error','control_error','cleanup_error'))
    device_errors=current and any(w[i] for i in (13,14,18,19,20,33))
    file_unresolved=h.get('file_pending_blocks',0) or h.get('file_writer_alive',False)
    completed=(report['host_exit_code']==0 and not errors and not device_errors and not file_unresolved
        and drained and (reached or stopped) and received>0 and difference is not None and difference>=0)
    report['transport_completed']=bool(completed)
    report['sustained_source_supply_verified']=bool(completed and not interrupted and measured and steady>=nominal*0.95)
    if completed:
        report['status']='completed_with_gaps' if interrupted else 'completed_with_loss' if (
            difference or h.get('file_dropped_bytes',0) or h.get('discarded_after_consumer_stop',0)) else 'passed'
    elif drained and not errors and not device_errors and not file_unresolved and report.get('interrupted_by_user'):
        report['status']='stopped_by_user'
    else: report['status']='failed'
    elapsed=h.get('elapsed_seconds',0)
    report['aggregate_host_bytes_per_second']=received/elapsed if elapsed>0 else None
    if raw_path is not None:
        size=raw_path.stat().st_size if raw_path.is_file() else None
        written=h.get('file_written_bytes');dropped=h.get('file_dropped_bytes',0)
        discarded=h.get('discarded_after_consumer_stop',0)
        report['raw_file']=dict(path=str(raw_path),bytes=size,reported_written_bytes=written,
            queue_dropped_bytes=dropped,discarded_after_consumer_stop=discarded,
            length_matches_writer=size is not None and size==written,
            accounted_host_bytes=written+dropped+discarded if written is not None else None,
            trailing_bytes=size%4 if size is not None else None,payload_inspected=False)
        if size is None or size!=written or written+dropped+discarded!=received:
            report['status']='failed';report['transport_completed']=False
            report['sustained_source_supply_verified']=False

def receive(args,*,executable=None):
    validate(args)
    if os.name!='nt': raise ValueError('native capture runs on Windows')
    selected=executable if executable is not None else getattr(args,'receiver_executable',None)
    program=Path(selected).resolve() if selected is not None else ROOT/'outputs/host/windows/sdr_receive.exe'
    if not program.is_file(): raise ValueError('build the Windows receiver before capture')
    floor=getattr(args,'experimental_b3_min_hz',None)
    unrestricted=getattr(args,'unrestricted_frequency',False)
    if floor is not None or unrestricted:
        verify_experimental_receiver(program,floor,unrestricted)
    command=[str(program),'--port',args.port,'--band',str(args.band),'--frequency-hz',str(args.frequency_hz),
        '--gain-index',str(args.gain_index),'--bandwidth-index',str(args.bandwidth_index),
        '--milliseconds',str(args.milliseconds),'--requests',str(args.requests),
        '--request-bytes',str(args.request_bytes),'--file-queue-blocks',str(args.file_queue_blocks)]
    raw=args.iq_output.resolve() if args.iq_output is not None else None
    if raw is not None:command+=['--output',str(raw)]
    if args.sync_file:command+=['--sync-file']
    report=dict(schema_version=1,started_at=datetime.now().astimezone().isoformat(),status='starting',
        backend='native_windows_session',command=command,interrupted_by_user=False,
        config=dict(port=args.port,band=args.band,frequency_hz=args.frequency_hz,gain_index=args.gain_index,
            bandwidth_index=args.bandwidth_index,duration_ms=args.milliseconds,
            requests=args.requests,request_bytes=args.request_bytes),
        format=dict(bytes_per_complex_sample=4,numeric_bits_per_lane=12,storage_bits_per_lane=16,
            byte_order='little',field_shift=4,lane_order_verified=False,
            sample_rate_nominal_hz=nominal_rate(args.bandwidth_index),sample_rate_measured=False,
            application_headers=False,application_crc=False,payload_hash=False))
    # Exclusive report creation before hardware access; preserve failure context.
    with args.output.open('x',encoding='utf-8') as stream:
        def save():
            stream.seek(0);json.dump(report,stream,ensure_ascii=False,indent=2);stream.write('\n');stream.truncate();stream.flush()
        save()
        try:
            with subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                                  creationflags=subprocess.CREATE_NEW_PROCESS_GROUP) as process:
                try: output,stderr=process.communicate()
                except KeyboardInterrupt:
                    report['interrupted_by_user']=True;save()
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                    output,stderr=process.communicate() # native STOP/drain owns shutdown
                report['host_exit_code']=process.returncode;report['host_stderr']=stderr
                report['host']=json.loads(output)
            summarize(report,raw)
        except Exception as error:
            report['status']='failed';report['error']=str(error)
        report['finished_at']=datetime.now().astimezone().isoformat();save()
    return report
