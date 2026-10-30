"""Compare offline planner with compiled actual AP/CP C profile implementation."""
import argparse,ctypes,hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from sdr.rf_catalog import INPUTS,catalog,plan_receive

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dll',type=Path,help='test an existing Windows host DLL instead of compiling the harness')
    parser.add_argument('--experimental-b3-min-hz',type=int)
    parser.add_argument('--output',type=Path,default=ROOT/'records/usb/rf-catalog-verification.json')
    parser.add_argument('--unrestricted-frequency',action='store_true')
    args=parser.parse_args()
    cross=ROOT/'work/windows-toolchain/root/usr'
    env=dict(os.environ);env['PATH']=str(cross/'bin')+os.pathsep+env.get('PATH','')
    build=ROOT/'work/rf-catalog-test';build.mkdir(exist_ok=True)
    harness=ROOT/'tools/verify/rf_catalog_harness.c';exe=build/'profile.exe'
    if args.dll:
        dll=args.dll.resolve();lib=ctypes.CDLL(str(dll))
        channel=lib.terminal_profile_channel;channel.argtypes=[ctypes.c_uint32,ctypes.c_uint32];channel.restype=ctypes.c_uint32
        anchor=lib.terminal_profile_anchor;anchor.argtypes=[ctypes.c_uint32];anchor.restype=ctypes.c_uint32
        def query(band,hz):
            ch=channel(band,hz)
            return [ch,anchor(ch)*100 if ch else 0]
    else:
        flags=[] if args.experimental_b3_min_hz is None else ['-DRXCAPT_EXPERIMENTAL_B3_MIN_RAW='+str(args.experimental_b3_min_hz//100)+'u']
        subprocess.run([str(cross/'bin/x86_64-w64-mingw32-gcc-posix'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
            '-static-libgcc',*flags,str(harness),str(ROOT/'firmware/capture/rxcapt_profile.c'),'-o',str(exe)],env=env,check=True)
        def query(band,hz):return list(map(int,subprocess.check_output([str(exe),str(band),str(hz)],text=True).split()))
    data=catalog(args.experimental_b3_min_hz,args.unrestricted_frequency);count=0
    for row in data['rows']:
        band=row['raw_band_id'];p=row['software_profile']
        if p:
            lo,hi=p['minimum_hz'],p['maximum_hz']
            frequencies={lo-100,lo,lo+1,lo+100,lo+99900,hi,hi+100,((lo+hi)//200)*100}
        else:
            frequencies={row['native_table']['minimum_hz']}
        for hz in sorted(frequencies):
            actual=query(band,hz)
            try: result=plan_receive(band,frequency_hz=hz,experimental_b3_min_hz=args.experimental_b3_min_hz,unrestricted_frequency=args.unrestricted_frequency)
            except ValueError: assert actual[0]==0,(band,hz,actual)
            else: assert actual==[result['initialization_channel'],result['initialization_frequency_hz']],(band,hz,actual,result)
            count+=1
    rows={r['raw_band_id']:r for r in data['rows']}
    assert rows[40]['software_profile']['minimum_hz']<rows[40]['native_table']['minimum_hz']
    assert rows[7]['calibration_rows_by_recorded_source']['historical_board'] is None
    assert rows[34]['calibration_rows_by_recorded_source']['historical_board']==13
    if rows[34]['software_integrated']:
        assert plan_receive(34,frequency_hz=2017500000)['initialization_channel']==36275
    for band,hz,gain in [(5,881500000,-1),(5,881500000,125),(True,881500000,40),(5,881500000.0,40)]:
        try: plan_receive(band,frequency_hz=hz,gain_index=gain)
        except ValueError: pass
        else: raise AssertionError('invalid argument accepted')
    dependencies=[ROOT/p for p in INPUTS]+[harness,Path(__file__),ROOT/'tools/sdr/rf_catalog.py',ROOT/'tools/sdr.py',ROOT/'firmware/capture/rxcapt_profile.h']
    if args.dll:dependencies.append(dll)
    report=dict(status='passed',device_accessed=False,hardware_tested=False,cases=count,
        native_table_rows=len(data['rows']),software_profiles=sum(r['software_integrated'] for r in data['rows']),
        scope='planner vs compiled current C AP channel selector and CP anchors at interior and boundary requests; recorded NV distinctions; no RF experiment',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies})
    report['experimental_b3_min_hz']=args.experimental_b3_min_hz
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
