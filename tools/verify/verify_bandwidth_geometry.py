"""Execute retained RX geometry code and compute conditional transport budgets.

No physical sample-rate measurement or new firmware configuration is implied.
"""
import argparse,hashlib,json,os,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from sdr.sample_rate import nominal_rate
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'records/usb/bandwidth-geometry-verification.json')
    args=parser.parse_args()
    cross=ROOT/'work/windows-toolchain/root/usr'
    env=dict(os.environ);env['PATH']=str(cross/'bin')+os.pathsep+env.get('PATH','')
    build=ROOT/'work/bandwidth-geometry';build.mkdir(exist_ok=True)
    harness=ROOT/'tools/verify/bandwidth_geometry_harness.c'
    source=ROOT/'firmware/rf_rebuild/rfad_raw_capture.c'
    exe=build/'geometry.exe'
    subprocess.run([str(cross/'bin/x86_64-w64-mingw32-gcc-posix'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
        '-ffunction-sections','-Wl,--gc-sections','-static-libgcc',str(harness),str(source),'-o',str(exe)],env=env,check=True)
    raw=subprocess.check_output([str(exe)],text=True)
    baseline=ROOT/'records/usb/fixed-hardware-baseline.json'
    fixed=next(r for r in json.loads(baseline.read_text())['tests'] if r['duration_ms']==60000)
    measured=fixed['steady_device_bytes_per_second']
    # Current ABI uses fixed byte slots independently of bandwidth geometry.
    abi=ROOT/'firmware/capture/rxcapt_finite_abi.h'
    slot=int(re.search(r'#define RXCAPT_FINITE_DATA_BYTES (\d+)u',abi.read_text())[1])
    rows=[]
    for line in raw.splitlines():
        bw,cycle,first,other,pre=map(int,line.split())
        rate=cycle*1000;required=rate*4
        assert rate==nominal_rate(bw)
        rows.append(dict(bandwidth_index=bw,cycle_words=cycle,first_block_words=first,
            other_block_words=other,rx_pre_cfg=hex(pre),cycle_bytes=cycle*4,
            inferred_sample_rate_hz_if_1ms_cycle=rate,required_bytes_per_second_if_1ms_cycle=required,
            ring_budget_ms_if_current_seven_slots=7*slot/required*1000,
            exceeds_measured_fixed_usb_rate=required>measured,
            fixed_usb_rate_to_required_ratio=measured/required,
            measured_sample_rate_hz=None,measured_effective_passband_hz=None,
            integration_scope='Offline geometry only; current deployment tracked separately in project-state',hardware_validated_in_current_service=False))
    assert len(rows)==6 and rows[4]['cycle_words']==rows[5]['cycle_words']
    dependencies=[Path(__file__),harness,source,abi,baseline,ROOT/'firmware/rf_rebuild/rfad_raw_capture.h',
        ROOT/'firmware/capture/rf_terminal_service.c',ROOT/'firmware/capture/generated/terminal_rxcapt_core.inc',
        ROOT/'firmware/sdr_receiver/bw0_usb_service.c',ROOT/'firmware/sdr_receiver/cp_usb_8910.c',
        ROOT/'firmware/rf_rebuild/rf_core_rxon_finish.c',ROOT/'firmware/sdr_receiver/sample_rate.h',ROOT/'tools/sdr/sample_rate.py']
    report=dict(status='passed',device_accessed=False,hardware_tested=False,
        scope='compiled retained C geometry and capacity checks for six BW indices; conditional 1ms-cycle transport budget, not native disassembly or physical rate proof',
        fixed_usb_60s_device_rate=measured,fixed_usb_60s_host_shortfall_bytes=fixed['device_minus_host_bytes'],
        rows=rows,implementation_dependencies=[
            'operation47 ABI1 remains16-byte BW0; optional ABI2 has20 bytes with explicit selected BW, matched module capability required',
            'CP operation13 carries packed selected BW; acceptance depends on compiled capability, not geometry alone',
            'AP and host share six nominal rates; BW4/BW5 saturate at30.72Msps; physical reference still required',
            'seven8000-byte DDR slots and AP address/length validation must remain consistent; do not enlarge DMA without reserved-space proof',
            'RX_PRE_CFG gets bandwidth<<8|8 after vendor RF profile; changing this register alone does not configure analog/DFE/FIR chain',
            'native fixed coefficient initialization and BW-to-mode propagation verified separately; physical decimation/clock/passband remain unverified',
            'BW4 and BW5 equal geometry does not prove equal analog or digital passband'],
        next_experiment='B40 BW0..BW5 representative and targeted-boundary comparison after matched BW5 candidate deployment',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies})
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
