"""Exercise the production DLL INFO parser on Windows; no device access."""
import argparse,ctypes,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dll',type=Path,default=ROOT/'outputs/host/windows/sdr_usb.dll')
    parser.add_argument('--output',type=Path,default=ROOT/'records/usb/host-info-verification.json')
    args=parser.parse_args()
    dll=args.dll.resolve()
    native=ctypes.CDLL(str(dll))
    parse=native.sdr_session_validate_info
    parse.argtypes=[ctypes.c_char_p,ctypes.c_uint32,ctypes.c_uint32]
    parse.restype=ctypes.c_uint32
    base=dict(firmware='uis8910-sdr-bw0-usb-v1',raw_usb=True,raw_usb_abi=1,bw0_usb=True,
              bw0_status_operation=44,bw0_start_operation=45,bw0_stop_operation=46,
              bw0_config_operation=47,bw0_recovery_status_operation=48,bw0_rf_profiles=[3,5,8,40])
    valid=json.dumps(base)
    cases=[(valid,5,True),(valid,7,False),(valid,40,True),
        (json.dumps(dict(base,extra={'text':'escaped " string','values':[None,False,-2.5e3]})),5,True),
        (valid+' garbage',5,False),(valid[:-1],5,False),(valid+'\0',5,False),
        (valid[:-1]+',"bw0_usb":false}',5,False),
        (valid.replace('"bw0_usb"','"bw0_\\u0075sb"'),5,False),
        (valid.replace('"raw_usb_abi": 1','"raw_usb_abi": 01'),5,False),
        (valid.replace('[3, 5, 8, 40]','[3, "5", 8, 40]'),5,False)]
    for key in base:
        missing=dict(base);del missing[key];cases.append((json.dumps(missing),5,False))
    nested=dict(base);del nested['bw0_usb'];nested['nested']={'bw0_usb':True}
    cases.append((json.dumps(nested),5,False))
    for text,band,expected in cases:
        data=text.encode();actual=parse(data,len(data),band)
        assert (actual==0)==expected,(text,band,actual)
    parse_bw=native.sdr_session_validate_info_bw
    parse_bw.argtypes=[ctypes.c_char_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32]
    parse_bw.restype=ctypes.c_uint32
    expanded=dict(base,bw0_bandwidth_indices=[0,1],bw0_config_abi=2)
    bw_cases=[(base,1,False),(expanded,1,True),(expanded,0,True),(expanded,2,False),
        (dict(expanded,bw0_bandwidth_indices=[0,1,2,3,4]),3,True),
        (dict(expanded,bw0_bandwidth_indices=[0,1,2,3,4]),4,True),
        (dict(expanded,bw0_bandwidth_indices=[0,1,2,3,4,5]),5,True),
        (dict(expanded,bw0_bandwidth_indices=[0,1,2,3,4]),5,False),
        (dict(expanded,bw0_bandwidth_indices=[0,1,2,3,4,5,6]),6,False),
        (dict(expanded,bw0_bandwidth_indices=[0,1,2]),2,True),
        (dict(expanded,bw0_bandwidth_indices=[0,1,2]),3,False),
        (dict(expanded,bw0_bandwidth_indices=[0,'2']),2,False),
        (dict(expanded,bw0_bandwidth_indices=[0,1,2],bw0_config_abi=1),2,False),
        (dict(expanded,bw0_config_abi=1),1,False),
        (dict(expanded,bw0_bandwidth_indices=[0]),1,False),
        (dict(expanded,bw0_bandwidth_indices=[0,'1']),1,False),
        (dict(expanded,bw0_bandwidth_indices=[1]),0,False)]
    for info,bw,expected in bw_cases:
        data=json.dumps(info).encode();actual=parse_bw(data,len(data),5,bw)
        assert (actual==0)==expected,(info,bw,actual)
    stream=native.sdr_session_validate_until_stop_info
    stream.argtypes=parse_bw.argtypes;stream.restype=ctypes.c_uint32
    capable=dict(expanded,bw0_until_stop=True,bw0_keepalive_operation=49,bw0_lease_timeout_ms=5000)
    stream_cases=[(expanded,False),(capable,True),(dict(capable,bw0_until_stop=False),False),
        (dict(capable,bw0_keepalive_operation=48),False),(dict(capable,bw0_lease_timeout_ms=0),False),
        (dict(capable,bw0_lease_timeout_ms=10000),False)]
    for info,expected in stream_cases:
        data=json.dumps(info).encode();assert (stream(data,len(data),5,1)==0)==expected
    deps=[Path(__file__),dll,ROOT/'host/windows/sdr_info.c',ROOT/'host/windows/sdr_session.h',ROOT/'host/windows/sdr_bandwidth.h']
    report=dict(status='passed',device_accessed=False,hardware_tested=False,cases=len(cases)+len(bw_cases)+len(stream_cases),
        scope='actual Windows DLL INFO JSON capability parser, no USB or serial open',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in deps})
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
