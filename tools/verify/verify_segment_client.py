"""Capability gating, segment wire decoder and configuration error paths."""
import hashlib,json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from sdr.segments import decode,decode_queue,decode_refill,summarize_refill,transact
class Client:
    def __init__(self,capable=True,fail=False,mismatch=False):self.capable=capable;self.fail=fail;self.mismatch=mismatch;self.calls=[]
    def info(self):return dict(firmware='uis8910-sdr-bw0-usb-v1',bw0_segment_profile_operation=51 if self.capable else 50,bw0_segment_profile_abi=1)
    def request(self,op,payload=b''):
        self.calls.append((op,payload))
        if payload and self.fail:raise ValueError('device BUSY')
        w=[0]*40;w[:3]=[0x31525055,1,0 if not payload or self.mismatch else struct.unpack('<2I',payload)[1]];w[37]=4
        return struct.pack('<40I',*w)
def main():
    c=Client();r={};transact(c,None,r);assert len(c.calls)==1 and not r.get('configuration_attempted')
    c=Client();r={};transact(c,1,r);assert c.calls[1]==(51,struct.pack('<2I',1,1)) and r['configuration_readback_verified']
    for c in (Client(False),Client(fail=True),Client(mismatch=True)):
        r={}
        try:transact(c,1,r)
        except ValueError:pass
        else:raise AssertionError('invalid capability/config result accepted')
        assert not r.get('configuration_readback_verified')
        if not c.capable:assert not c.calls
    w=[0]*40;w[:3]=[0x31525055,1,1];w[6]=2;w[7]=100;w[10]=2;w[37]=4
    assert decode(struct.pack('<40I',*w))['stages']['prepare']['mean_elapsed_us']==50
    for data in (b'',bytes(159),bytes(160),struct.pack('<40I',*(w[:10]+[1]+w[11:]))):
        try:decode(data)
        except ValueError:pass
        else:raise AssertionError('malformed final stats accepted')
    w[37]=3;w[10]=1;assert not decode(struct.pack('<40I',*w))['counter_snapshot_final']
    q=[0]*16;q[:5]=[0x31515055,1,1,8,4];q[6:8]=[4,2];q[11:15]=[1,125,0,125]
    parsed=decode_queue(struct.pack('<16I',*q));assert parsed['interval_total_us']==125 and parsed['empty_after_completions']==2
    class QueueClient(Client):
        def info(self):return dict(super().info(),bw0_queue_profile_abi=1)
        def request(self,op,payload=b''):
            self.calls.append((op,payload));assert payload==struct.pack('<I',2);return struct.pack('<16I',*q)
    c=QueueClient();r={};transact(c,None,r,True);assert len(c.calls)==1 and r['queue']['closed_intervals']==1
    c=Client();r={}
    try:transact(c,None,r,True)
    except ValueError:assert not c.calls
    else:raise AssertionError('old firmware accepted queue operation')
    for bad in (b'',bytes(63),bytes(64),struct.pack('<16I',*(q[:7]+[5]+q[8:]))):
        try:decode_queue(bad)
        except ValueError:pass
        else:raise AssertionError('malformed queue stats accepted')
    rw=[0]*202;rw[:10]=[0x31524655,1,1,9,4,1,1,0,0,1]
    rw[10:18]=[1,31,0,10,20,30,40,0xe01]
    parsed=decode_refill(struct.pack('<202I',*rw))
    assert parsed['episodes'][0]['observations_us']['first_worker']==0
    assert parsed['episodes'][0]['first_worker_context']['mailbox_operation']==14
    intervals=parsed['summary']['intervals']
    assert intervals['empty_to_worker']['median_us']==0
    assert intervals['release_request_to_ack']['median_us']==10
    assert intervals['empty_to_refill']['median_us']==40
    # Real publications can be observed before an earlier release ACK.
    # Missing and saturated observations must not invent causal latency.
    observations=parsed['episodes'][0]['observations_us']
    cases=[dict(state='refilled',end_us=80,observations_us=dict(observations,published_hint_observed=5)),
        dict(state='refilled',end_us=90,observations_us=dict(observations,release_request_observed=None)),
        dict(state='refilled',end_us=0xffffffff,observations_us=observations),
        dict(state='aborted',end_us=10,observations_us=observations),
        dict(state='open',end_us=None,observations_us=observations)]
    summary=summarize_refill(cases);intervals=summary['intervals']
    assert summary['retained_refilled_episodes']==3 and summary['retained_aborted_episodes']==1 and summary['retained_open_episodes']==1
    assert intervals['ack_to_published_hint']['reversed_order']==1
    assert intervals['release_request_to_ack']['missing']==1
    assert intervals['empty_to_refill']['saturated']==1 and intervals['empty_to_refill']['median_us']==85
    class RefillClient(Client):
        def info(self):return dict(super().info(),bw0_refill_profile_abi=1)
        def request(self,op,payload=b''):
            self.calls.append((op,payload));assert payload==struct.pack('<I',3)
            return struct.pack('<202I',*rw)
    c=RefillClient();r={};transact(c,None,r,refill=True);assert r['refill']['refilled']==1
    c=Client();r={}
    try:transact(c,None,r,refill=True)
    except ValueError:assert not c.calls
    else:raise AssertionError('old firmware accepted refill query')
    bads=[b'',bytes(808)]
    for index,value in ((9,25),(11,63),(14,41),(18,1),(6,0)):
        bad=rw.copy();bad[index]=value;bads.append(struct.pack('<202I',*bad))
    for bad in bads:
        try:decode_refill(bad)
        except ValueError:pass
        else:raise AssertionError('malformed refill stats accepted')
    # Active row needs an unterminated final episode and zero end offset.
    active=rw.copy();active[6]=0;active[8]=1;active[11]=15;active[16]=0
    assert decode_refill(struct.pack('<202I',*active))['episodes'][0]['state']=='open'
    for index,value in ((11,31),(16,1)):
        bad=active.copy();bad[index]=value
        try:decode_refill(struct.pack('<202I',*bad))
        except ValueError:pass
        else:raise AssertionError('inconsistent active episode accepted')
    report=dict(status='passed',hardware_tested=False,device_accessed=False,
        scope='synthetic operation51 replies, capability gating, BUSY/readback mismatch, final histograms, refill active/terminal validation, missing/reversed/saturated AP observations and summary populations; no serial or physical timing',
        dependencies={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ('tools/sdr/segments.py','tools/verify/verify_segment_client.py')})
    out=ROOT/'records/usb/bw2-v8-segment-client-verification.json';out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
