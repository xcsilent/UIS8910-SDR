"""Exercise shared Auto resolver in built Windows DLL; no hardware access."""
from pathlib import Path
import argparse,ctypes,hashlib,json
ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dll',type=Path,default=ROOT/'outputs/host/windows/sdr_usb.dll')
    parser.add_argument('--output',type=Path,default=ROOT/'records/host/auto-shared-resolver-verification.json')
    parser.add_argument('--lowband-extension',action='store_true')
    parser.add_argument('--b3-lower-extension',action='store_true',help='verify delivered1375MHz B3 request envelope')
    args=parser.parse_args()
    dll=args.dll.resolve()
    lib=ctypes.CDLL(str(dll));fn=lib.sdr_session_auto_route
    fn.argtypes=[ctypes.c_char_p]+[ctypes.c_uint32]*5+[ctypes.POINTER(ctypes.c_uint32)]
    fn.restype=ctypes.c_uint32
    source=ROOT/'records/rf/mainline-resume-identity.json'
    info=json.loads(source.read_text())['firmware'];count=0
    def check(hz,current,expected,config=None,bw=0,continuous=0):
        nonlocal count
        raw=json.dumps(info if config is None else config).encode();out=ctypes.c_uint32(999)
        e=fn(raw,len(raw),hz,current,bw,continuous,ctypes.byref(out))
        assert (e==0 and out.value==expected) if expected else e!=0,(hz,current,e,out.value,expected)
        count+=1
    for hz,current,expected in [(824000000,0,5),(880000000,8,5),(915000000,8,5),
        (917500000,5,5),(917500000,8,8),(920000000,5,8),(925000000,0,8),
        (925000100,0,8),(1000000000,0,8),(1000000100,0,0),(1710000000,0,3),
        (1885000000,40,3),(1890000000,40,3),(1890000100,40,40),
        (1900000000,3,3),(1900000000,40,40),(2000000000,0,40),
        (2790625000,0,40),(2790625100,0,0),(881500001,0,0),(0,0,0)]:check(hz,current,expected)
    for hz in (1650000000,1680000000,1709999900):
        for current in (0,3):check(hz,current,3 if args.b3_lower_extension else 0)
    if args.b3_lower_extension:
        for hz in (1375000000,1400000000,1447000000,1500000000,1600000000):
            for current in (0,5,40):check(hz,current,3)
        for hz in (1000000100,1300000000,1350000000,1374999900,1920000100):
            check(hz,3,40 if hz==1920000100 else 0)
        check(1375000000,3,0,dict(info,bw0_rf_profiles=[5,8,40]))
    if args.lowband_extension:
        for hz,expected in [(499999900,0),(500000000,5),(700000000,5),(800000000,5),(823999900,5)]:check(hz,0,expected)
    missing=dict(info,bw0_rf_profiles=[3,8]);check(1900000000,40,3,missing);check(2600000000,40,0,missing)
    for config in [dict(info,firmware='other'),dict(info,bw0_config_operation=99),dict(info,bw0_rf_profiles=[])]:
        check(881500000,5,0,config)
    check(881500000,5,5,bw=2,continuous=1)
    check(881500000,5,0,bw=3)
    check(881500000,5,0,dict(info,bw0_until_stop=False),continuous=1)
    malformed=b'{"firmware":"uis8910-sdr-bw0-usb-v1","firmware":"other"}'
    out=ctypes.c_uint32();assert fn(malformed,len(malformed),881500000,5,0,0,ctypes.byref(out))!=0
    paths=[Path(__file__),dll,ROOT/'host/common/rf_auto.h',ROOT/'host/windows/sdr_info.c',ROOT/'firmware/capture/rxcapt_profile.c',source]
    report=dict(status='passed',device_accessed=False,cases=count+1,
        scope='Actual Windows DLL resolver; identity/duplicate keys, advertised availability, gaps/grid, sticky overlaps, BW and continuous gates; runtime NV still checked by firmware CONFIG.',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
