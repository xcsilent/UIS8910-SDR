"""Independent scheduler control/statistics; never touches IQ or RF settings."""
from datetime import datetime
import hashlib,json,struct,sys
from pathlib import Path
from .rf_catalog import ROOT

def decode(data):
    if len(data) not in (128,136):raise ValueError('scheduler reply must be128 or136bytes')
    w=list(struct.unpack('<'+str(len(data)//4)+'I',data))
    if w[0]!=0x31484353 or {1:128,2:136}.get(w[1])!=len(data) or w[29]!=8:raise ValueError('unsupported scheduler ABI')
    if w[1]==2 and (w[32]>1 or w[33]>5):raise ValueError('invalid scheduler policy state')
    sleep=w[10]+(w[11]<<32);ack=w[14]+(w[15]<<32)
    return dict(words=w,policy_mode=('manual' if w[32] else 'automatic') if w[1]==2 else 'unknown',
        selected_bandwidth_index=w[33] if w[1]==2 else None,wait_us=w[2],burst_us=w[3],wait_calls=w[4],notification_hits=w[5],
        sleep_calls=w[6],fast_polls=w[7],burst_exhaustions=w[8],ticks=w[9],sleep_elapsed_us=sleep,
        maximum_sleep_us=w[12],mean_sleep_us=sleep/w[6] if w[6] else None,
        observed_ack_count=w[13],observed_ack_elapsed_us=ack,maximum_ack_us=w[16],
        mean_observed_ack_us=ack/w[13] if w[13] else None,sleep_histogram=w[17:23],ack_histogram=w[23:29],
        histogram_upper_edges_us=[50,100,250,500,1000,None],maximum_fast_polls_per_burst=w[29],epoch=w[30],phase=w[31],
        counter_snapshot_final=w[31] in (0,4),
        timing_scope='OS elapsed wait and AP-observed stream ACK latency; not device CPU cycles or CP execution time alone')

def scheduler(args):
    output=args.output.resolve()
    if not output.is_relative_to(ROOT) or output.exists() or not output.parent.is_dir():raise ValueError('choose a new project report in an existing directory')
    wait=getattr(args,'wait_us',None);burst=getattr(args,'burst_us',None)
    automatic=getattr(args,'auto',False)
    if automatic and (wait is not None or burst is not None):raise ValueError('--auto cannot be combined with explicit wait/burst')
    if (wait is None)!=(burst is None) or wait is not None and (not 25<=wait<=1000 or not 0<=burst<=50):
        raise ValueError('provide both wait25..1000us and burst0..50us, or neither for a read-only query')
    report=dict(recorded_at=datetime.now().astimezone().isoformat(),status='starting',device_accessed=False,
        configuration_requested=automatic or wait is not None,read_only=not automatic and wait is None,scheduler_operation_sent=False,
        configuration_attempted=False,configuration_readback_verified=False,
        firmware_changed=False,RF_settings_changed=False,reset_performed=False)
    import serial
    sys.path.insert(0,str(ROOT/'tools/debug'))
    from uis_debug import Client
    with output.open('x',encoding='utf-8') as stream:
        def save():stream.seek(0);json.dump(report,stream,indent=2);stream.write('\n');stream.truncate();stream.flush()
        save()
        try:
            with serial.Serial(args.port,115200,timeout=.1) as port:
                client=Client(port,5);report['device_accessed']=True;info=client.info();report['firmware']=info
                if info.get('firmware')!='uis8910-sdr-bw0-usb-v1' or info.get('bw0_scheduler_operation')!=50 or info.get('bw0_scheduler_abi')!=1:
                    raise ValueError('firmware does not advertise scheduler operation50/ABI1; no scheduler command sent')
                policy=info.get('bw0_scheduler_policy_abi')==2
                if automatic and not policy:raise ValueError('firmware does not support automatic scheduler policy; no scheduler command sent')
                minimum=info.get('bw0_scheduler_auto_wait_min_bw',5)
                if automatic and (type(minimum) is not int or not 0<=minimum<=5):raise ValueError('unsupported automatic wait threshold; no scheduler command sent')
                report['scheduler_operation_sent']=True
                query=struct.pack('<I',2) if policy else b''
                report['before']=decode(client.request(50,query))
                if automatic or wait is not None:
                    report['configuration_attempted']=True
                    client.request(50,struct.pack('<3I',2,0,0) if automatic else struct.pack('<3I',1,wait,burst))
                    report['after']=decode(client.request(50,query))
                    if automatic:
                        if report['after']['policy_mode']!='automatic' or report['after']['burst_us'] or report['after']['wait_us']!=(100 if report['after']['selected_bandwidth_index']>=minimum else 250):raise ValueError('automatic scheduler readback mismatch')
                    elif (report['after']['wait_us'],report['after']['burst_us'])!=(wait,burst) or policy and report['after']['policy_mode']!='manual':raise ValueError('scheduler configuration readback mismatch')
                    report['configuration_readback_verified']=True
                report['status']='passed'
        except Exception as error:report.update(status='failed',error=str(error))
        report['dependencies']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ('tools/sdr/scheduler.py','tools/debug/uis_debug.py')}
        save()
    return report
