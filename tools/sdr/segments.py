"""Separate USB segment statistics/configuration; raw IQ remains untouched."""
from datetime import datetime
import hashlib,json,struct,sys
from statistics import median
from .rf_catalog import ROOT

def decode(data):
    if len(data)!=160:raise ValueError('segment reply must be160bytes')
    w=list(struct.unpack('<40I',data))
    if w[:2]!=[0x31525055,1] or w[2]>1 or any(w[38:]):raise ValueError('unsupported segment profile ABI')
    final=w[37] in (0,4)
    stages={}
    for i,name in enumerate(('prepare','enqueue_call','submit_to_callback')):
        at=6+10*i;count=w[at];total=w[at+1]+(w[at+2]<<32);hist=w[at+4:at+10]
        if final and sum(hist)!=count:raise ValueError('final segment histogram/count mismatch')
        stages[name]=dict(count=count,total_elapsed_us=total,maximum_elapsed_us=w[at+3],
            mean_elapsed_us=total/count if count else None,histogram=hist)
    return dict(words=w,enabled=bool(w[2]),exchanges=w[3],released_blocks=w[4],claimed_blocks=w[5],
        mean_claimed_blocks_per_exchange=w[5]/w[3] if w[3] else None,
        mean_released_blocks_per_exchange=w[4]/w[3] if w[3] else None,
        stages=stages,histogram_upper_edges_us=[10,25,50,100,250,None],epoch=w[36],phase=w[37],
        counter_snapshot_final=final,timing_scope='elapsed wall time including preemption; completion waits overlap; do not sum as CPU utilization')

def decode_queue(data):
    if len(data)!=64:raise ValueError('queue reply must be64bytes')
    w=struct.unpack('<16I',data)
    if w[:2]!=(0x31515055,1) or w[2]>1 or w[15]>1:raise ValueError('unsupported queue profile ABI')
    if w[7]>w[6] or w[11]>w[7]:raise ValueError('queue profile counters inconsistent')
    return dict(abi=1,enabled=bool(w[2]),epoch=w[3],phase=w[4],accepted_outstanding=w[5],
        asynchronous_successful_completions=w[6],empty_after_completions=w[7],synchronous_completions=w[8],
        rejected=w[9],cancelled_or_failed=w[10],closed_intervals=w[11],
        interval_total_us=w[12]+(w[13]<<32),interval_max_us=w[14],interval_open=bool(w[15]),
        scope='Current/last adapter open, not necessarily whole session. Time ends after successful enqueue returns; not hardware idle time. Synchronous completions do not classify intervals. Stop/fault may leave an open, uncounted interval.')

def summarize_refill(rows):
    """Compare AP observations only, without imposing a causal event order."""
    pairs=(('empty_to_worker',None,'first_worker'),
        ('worker_to_release_request','first_worker','release_request_observed'),
        ('release_request_to_ack','release_request_observed','release_ack_observed'),
        ('ack_to_published_hint','release_ack_observed','published_hint_observed'),
        ('published_hint_to_refill','published_hint_observed','end'),
        ('empty_to_refill',None,'end'))
    successful=[r for r in rows if r['state']=='refilled']
    intervals={}
    for name,begin,end in pairs:
        samples=[];missing=reversed_order=saturated=0
        for row in successful:
            values=dict(row['observations_us'],end=row['end_us'])
            first=0 if begin is None else values[begin];last=values[end]
            if first is None or last is None:missing+=1
            elif first==0xffffffff or last==0xffffffff:saturated+=1
            elif last<first:reversed_order+=1
            else:samples.append(last-first)
        intervals[name]=dict(count=len(samples),missing=missing,reversed_order=reversed_order,saturated=saturated,
            median_us=median(samples) if samples else None,
            mean_us=sum(samples)/len(samples) if samples else None,
            maximum_us=max(samples) if samples else None)
    return dict(retained_refilled_episodes=len(successful),
        retained_aborted_episodes=sum(r['state']=='aborted' for r in rows),
        retained_open_episodes=sum(r['state']=='open' for r in rows),intervals=intervals,
        scope='Only retained successful episodes. Each interval has its own eligible population; medians are not additive. Published data may be observed before release ACK, so reversed pairs are counted, not treated as corruption or negative latency. Missing observations can predate the episode. Last24 episodes do not estimate session-wide prevalence or physical idle time.')

def decode_refill(data):
    if len(data)!=808:raise ValueError('refill reply must be808bytes')
    w=struct.unpack('<202I',data)
    if w[:2]!=(0x31524655,1) or w[2]>1 or w[8]>1 or w[9]!=min(w[5],24):
        raise ValueError('unsupported refill profile ABI')
    if w[6]+w[7]+w[8]!=w[5]:raise ValueError('refill episode counters inconsistent')
    rows=[]
    names=('first_worker','release_request_observed','release_ack_observed','published_hint_observed')
    for i in range(24):
        row=w[10+i*8:18+i*8]
        if i>=w[9]:
            if any(row):raise ValueError('nonzero unused refill row')
            continue
        seq,flags,*_=row
        if seq!=w[5]-w[9]+i+1 or flags&~63 or flags&48==48:
            raise ValueError('invalid refill row identity/flags')
        terminal=bool(flags&48)
        if not terminal and (not w[8] or i!=w[9]-1):raise ValueError('invalid open refill episode')
        if not terminal and row[6]:raise ValueError('end offset without terminal state')
        if terminal and i==w[9]-1 and w[8]:raise ValueError('active episode marked terminal')
        if any(row[2+j] and not flags&(1<<j) for j in range(4)):
            raise ValueError('refill offset without observation')
        if terminal and any(row[2+j]>row[6] for j in range(4) if flags&(1<<j)):
            raise ValueError('refill event after terminal observation')
        if not flags&1 and row[7]:raise ValueError('refill context without worker')
        rows.append(dict(sequence=seq,state='refilled' if flags&16 else 'aborted' if flags&32 else 'open',
            observations_us={name:row[2+j] if flags&(1<<j) else None for j,name in enumerate(names)},
            end_us=row[6] if terminal else None,
            first_worker_context=dict(mailbox_pending=bool(row[7]&1),published_hint_available=bool(row[7]&2),
                mailbox_operation=row[7]>>8) if flags&1 else None))
    return dict(abi=1,enabled=bool(w[2]),epoch=w[3],phase=w[4],opened=w[5],refilled=w[6],aborted=w[7],
        active=bool(w[8]),retained=w[9],episodes=rows,summary=summarize_refill(rows),
        scope='Last24 application-observed empty-queue episodes, not representative sampling. Offsets start at the empty completion and overlap; do not add. Request/ACK/publication observations are AP timestamps, not CP event times. End is enqueue return or abort. Missing observations may precede the episode. UINT32_MAX offsets are saturated. No payload, CPU, physical USB idle or sample-loss measurement.')

def transact(client,enabled,report,queue=False,refill=False):
    report['firmware']=info=client.info()
    if info.get('firmware')!='uis8910-sdr-bw0-usb-v1' or info.get('bw0_segment_profile_operation')!=51 or info.get('bw0_segment_profile_abi')!=1:
        raise ValueError('firmware lacks segment operation51/ABI1; no profile command sent')
    if queue and refill:raise ValueError('choose queue or refill query')
    if refill:
        if enabled is not None:raise ValueError('refill read cannot change profile configuration')
        if info.get('bw0_refill_profile_abi')!=1:raise ValueError('firmware lacks refill profile ABI1; no refill command sent')
        report['profile_operation_sent']=True;report['refill']=decode_refill(client.request(51,struct.pack('<I',3)));return
    if queue:
        if enabled is not None:raise ValueError('queue read cannot change profile configuration')
        if info.get('bw0_queue_profile_abi')!=1:raise ValueError('firmware lacks queue profile ABI1; no queue command sent')
        report['profile_operation_sent']=True;report['queue']=decode_queue(client.request(51,struct.pack('<I',2)));return
    report['profile_operation_sent']=True;report['before']=decode(client.request(51))
    if enabled is not None:
        report['configuration_attempted']=True
        report['after']=decode(client.request(51,struct.pack('<2I',1,enabled)))
        if report['after']['enabled']!=bool(enabled):raise ValueError('segment enable readback mismatch')
        report['configuration_readback_verified']=True

def segments(args):
    output=args.output.resolve();enabled=args.enabled
    if not output.is_relative_to(ROOT) or output.exists() or not output.parent.is_dir():raise ValueError('choose a new project report in an existing directory')
    if enabled not in (None,0,1):raise ValueError('enabled must be0or1')
    import serial
    sys.path.insert(0,str(ROOT/'tools/debug'))
    from uis_debug import Client
    report=dict(recorded_at=datetime.now().astimezone().isoformat(),status='starting',device_accessed=False,
        read_only=enabled is None,configuration_requested=enabled is not None,profile_operation_sent=False,
        configuration_attempted=False,configuration_readback_verified=False,firmware_changed=False,RF_settings_changed=False,reset_performed=False)
    with output.open('x',encoding='utf-8') as stream:
        def save():stream.seek(0);json.dump(report,stream,indent=2);stream.write('\n');stream.truncate();stream.flush()
        save()
        try:
            with serial.Serial(args.port,115200,timeout=.1) as port:
                client=Client(port,5);report['device_accessed']=True;transact(client,enabled,report,getattr(args,'queue',False),getattr(args,'refill',False));report['status']='passed'
        except Exception as error:report.update(status='failed',error=str(error))
        report['dependencies']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ('tools/sdr/segments.py','tools/debug/uis_debug.py')};save()
    return report
