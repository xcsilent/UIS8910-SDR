"""Check experimental 6+1 capture geometry and linked AP/CP binding."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--cp-build',type=Path,required=True,help='explicit matching CP build')
parser.add_argument('--ap-build',type=Path,required=True,help='explicit matching AP build')
parser.add_argument('--output',type=Path,default=root/'records/usb/geometry-lossy-scratch-layout.json')
args=parser.parse_args()
cp_path=args.cp_build.resolve()
ap_path=args.ap_build.resolve()
cp=json.loads(cp_path.read_text());ap=json.loads(ap_path.read_text())
assert cp['experimental_lossy_scratch'] and cp['slot_bytes']==8192
sys.path.insert(0,str(root/'tools'))
from sdr.capture_layout import validate
trace=cp.get('rf_status_trace',{})
trace_address=int(trace['address'],0) if trace.get('enabled') else None
if trace_address is not None:
    assert trace_address==0x8096e000 and trace['bytes'] in (256,512)
validate(0x80960000,8192,7,2047,0x8096e300,trace_address,trace.get('bytes',0),
         reserved=[('digital profile',0x8096e200,64)])
assert int(cp['ap_mailbox'],0)==int(ap['ap_mailbox'],0)
assert Path(ap['cp_modules'].replace('\\','/')).as_posix()==cp_path.relative_to(root).as_posix()
data=0x80960000;size=8192;head=0x8096ff00
output=(data,data+6*size);scratch=(output[1],output[1]+size)
output_head=(head,head+6*24);scratch_head=(output_head[1],output_head[1]+24)
assert all(x%32==0 for x in (*output,*scratch))
assert scratch[1]<=0x8096e300 and scratch_head[1]<=0x80970000
assert cp['resident']['bytes']<=0x4000
assert hashlib.sha256((root/cp['resident']['path']).read_bytes()).hexdigest()==cp['resident']['sha256']
assert hashlib.sha256((root/ap['appimg']).read_bytes()).hexdigest()==ap['appimg_sha256']
result={'status':'passed','device_accessed':False,'hardware_tested':False,
        'output_data':[hex(x) for x in output],'scratch_data':[hex(x) for x in scratch],
        'output_head':[hex(x) for x in output_head],'scratch_head':[hex(x) for x in scratch_head],
        'rf_status_trace':trace,'head_cache_line_shared':True,'ap_mailbox':ap['ap_mailbox'],
        'scope':'Declared address geometry and linked manifest/hash checks; HEAD 24-byte records share cache lines; DMA reachability, cache coherence and physical synchronization unverified.',
        'dependencies':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),cp_path,ap_path)}}
args.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
