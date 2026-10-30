"""Execute the production scheduling policy with synthetic clock and events."""
import argparse,hashlib,json,struct,subprocess,sys,tempfile,types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def verify_client():
    from sdr.scheduler import scheduler
    state=dict(policy=True,wait=250,burst=0,manual=1,bw=5,minimum=2);calls=[]
    class Transport:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    class Client:
        def __init__(self,*args):pass
        def info(self):return dict(firmware='uis8910-sdr-bw0-usb-v1',bw0_scheduler_operation=50,bw0_scheduler_abi=1,**({'bw0_scheduler_policy_abi':2} if state['policy'] else {}),**({'bw0_scheduler_auto_wait_min_bw':state['minimum']} if state['minimum']!=5 else {}))
        def request(self,op,payload=b''):
            assert op==50;calls.append(payload)
            if len(payload)==12:
                version,wait,burst=struct.unpack('<3I',payload)
                if version==2:state.update(manual=0,wait=100 if state['bw']>=state['minimum'] else 250,burst=0)
                else:state.update(manual=1,wait=wait,burst=burst)
            extended=payload[:4]==struct.pack('<I',2)
            w=[0]*(34 if extended else 32);w[:4]=[0x31484353,2 if extended else 1,state['wait'],state['burst']];w[29]=8;w[31]=4
            if extended:w[32:]=[state['manual'],state['bw']]
            return struct.pack('<'+str(len(w))+'I',*w)
    previous={k:sys.modules.get(k) for k in ('serial','uis_debug')}
    sys.modules['serial']=types.SimpleNamespace(Serial=lambda *a,**k:Transport());sys.modules['uis_debug']=types.SimpleNamespace(Client=Client)
    try:
        with tempfile.TemporaryDirectory(dir=ROOT/'work') as temp:
            def run(name,automatic=False,wait=None,burst=None):
                return scheduler(types.SimpleNamespace(output=Path(temp)/(name+'.json'),port='COM_TEST',auto=automatic,wait_us=wait,burst_us=burst))
            r=run('auto',True);assert r['status']=='passed' and r['after']['policy_mode']=='automatic' and r['after']['wait_us']==100
            r=run('manual',wait=75,burst=20);assert r['status']=='passed' and r['after']['policy_mode']=='manual'
            state['bw']=2;r=run('wide-bw2',True);assert r['status']=='passed' and r['after']['wait_us']==100
            state['minimum']=5;r=run('v26-bw2',True);assert r['status']=='passed' and r['after']['wait_us']==250
            state['policy']=False;calls.clear()
            r=run('unsupported-auto',True);assert r['status']=='failed' and not calls and not r['scheduler_operation_sent']
            r=run('legacy-manual',wait=250,burst=0);assert r['status']=='passed' and r['after']['policy_mode']=='unknown'
            assert calls==[b'',struct.pack('<3I',1,250,0),b'']
    finally:
        for k,v in previous.items():
            if v is None:sys.modules.pop(k,None)
            else:sys.modules[k]=v
    return ['policy ABI2 automatic/manual readback','ABI1 legacy query/config preserved','unsupported automatic rejected before operation50']
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'records/usb/scheduler-policy-native.json')
    args=parser.parse_args()
    build=ROOT/'work/usb-scheduler';build.mkdir(exist_ok=True)
    source=ROOT/'firmware/sdr_receiver/cp_usb_scheduler.c';header=source.with_suffix('.h')
    harness=ROOT/'tools/verify/cp_usb_scheduler_harness.c';exe=build/'scheduler'
    subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-fsanitize=undefined',
        '-fno-sanitize-recover=all',str(source),str(harness),'-o',str(exe)],check=True)
    result=subprocess.check_output([str(exe)],text=True).strip()
    sys.path.insert(0,str(ROOT/'tools'))
    from sdr.scheduler import decode
    words=[0]*32;words[:4]=[0x31484353,1,50,40];words[6]=2;words[10]=600;words[13]=2;words[14]=800;words[29]=8;words[31]=4
    decoded=decode(struct.pack('<32I',*words));assert decoded['mean_sleep_us']==300 and decoded['mean_observed_ack_us']==400 and decoded['counter_snapshot_final']
    assert decoded['policy_mode']=='unknown'
    extended=words+[0,5];extended[1]=2;extended[2:4]=[100,0]
    auto=decode(struct.pack('<34I',*extended));assert auto['policy_mode']=='automatic' and auto['selected_bandwidth_index']==5
    extended[32]=1;assert decode(struct.pack('<34I',*extended))['policy_mode']=='manual'
    extended[32]=2
    for data in (b'',bytes(127),bytes(128),struct.pack('<34I',*extended),struct.pack('<34I',*(words+[0,5]))):
        try:decode(data)
        except ValueError:pass
        else:raise AssertionError('invalid scheduler wire response accepted')
    client_tests=verify_client()
    report=dict(status='passed',device_accessed=False,hardware_tested=False,result=result,client_tests=client_tests,
        scope='actual pure scheduler C with synthetic time and notifications; no OS wait latency, CP response or throughput proof',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,header,harness,Path(__file__),ROOT/'tools/sdr/scheduler.py']})
    output=args.output;output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
