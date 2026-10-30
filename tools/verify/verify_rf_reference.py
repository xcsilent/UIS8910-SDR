"""Synthetic RF evidence checks: signed12 orientation, busy noise and TX-off.

No hardware access; these tests do not prove real RF reception.
"""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from rf_reference import spectrum, assess, finish_transmitter, capture_terminal, reference_configurations, route_label
from rf_reference import fem_configurations,run,run_sweep
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch


def check_b3_candidate():
    """Run the B3 orchestration with fake RX/TX; mismatches must fail first."""
    cases=[]
    for scenario in ('valid','valid-first','wrong-host-floor','changed-dll','changed-exe','missing-artifact','wrong-cp-floor'):
        with tempfile.TemporaryDirectory(dir=ROOT/'work',prefix='b3-reference-test-') as directory:
            folder=Path(directory);exe=folder/'sdr_receive.exe';dll=folder/'sdr_usb.dll'
            exe.write_bytes(b'fake receiver');dll.write_bytes(b'fake library')
            artifacts=[dict(path=p.relative_to(ROOT).as_posix(),bytes=p.stat().st_size,
                sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in (exe,dll)]
            host=dict(experimental_b3_min_hz=1650000000,artifacts=artifacts)
            if scenario=='wrong-host-floor':host['experimental_b3_min_hz']=1660000000
            if scenario=='missing-artifact':host['artifacts']=artifacts[:1]
            (folder/'build.json').write_text(json.dumps(host),encoding='utf-8')
            if scenario=='changed-dll':dll.write_bytes(b'changed library')
            if scenario=='changed-exe':exe.write_bytes(b'changed receiver')
            cp=folder/'cp.json';cp.write_text(json.dumps(dict(experimental_b3_min_hz=
                1660000000 if scenario=='wrong-cp-floor' else 1650000000,
                rf_status_trace=dict(enabled=True,abi=5))),encoding='utf-8')
            config=SimpleNamespace(port='MOCK',band=3,frequency_hz=1680000000,gain_index=40,
                bandwidth_index=0,output=folder/'report.json',data_dir=folder/'data',
                serial='MOCK',tx_gain=0,dma_block_bytes=8192,rf_status_cp_build=cp,
                receiver_executable=exe,experimental_b3_min_hz=1650000000,
                rf_snapshot_policy='first' if scenario=='valid-first' else 'all')
            received=[];children=[]
            def receive(args,**kwargs):
                assert args.experimental_b3_min_hz==1650000000 and kwargs['executable']==exe
                received.append(args.frequency_hz)
                return dict(transport_completed=True,host=dict(device_drained=True,epoch=len(received)))
            class Child:
                def __init__(self,*args,**kwargs):
                    self.returncode=None;self.pid=123;children.append(self)
                    kwargs['stdout'].write('Press Ctrl + C\n');kwargs['stdout'].flush()
                def poll(self):return self.returncode
                def wait(self,timeout):self.returncode=0;return 0
                def terminate(self):self.returncode=-1
                def kill(self):self.returncode=-1
            with patch('rf_reference.receive',receive),patch('rf_reference.subprocess.Popen',Child),\
                 patch('sdr.rf_status.snapshot',return_value=dict(status='passed')) as snapshots,\
                 patch('rf_reference.spectrum',return_value=dict(target_power=1.,peak_hz=150000)),\
                 patch('rf_reference.assess',return_value=dict(status='reference_verified',reference_identified=True)):
                if scenario in ('valid','valid-first'):
                    result=run(config)
                    assert result['status']=='reference_verified' and len(children)==2
                    assert received==[1680000000,1680000000,1680100000,1680000000]
                    assert snapshots.call_count==(1 if scenario=='valid-first' else 4)
                    assert [t['finite_samples'] for t in result['transmissions']]==([8000000,6000000] if scenario=='valid-first' else [16000000,10000000])
                else:
                    try:run(config)
                    except ValueError:pass
                    else:raise AssertionError('candidate mismatch accepted: '+scenario)
                    assert not received and not children and not config.output.exists()
            cases.append(dict(scenario=scenario,captures=len(received),tx_children=len(children)))
    return cases


def check_sweep():
    cases=[]
    for scenario in ('complete','missing-reference','transport-failed','undrained','tx-unconfirmed','exception'):
        with tempfile.TemporaryDirectory(dir=ROOT/'work',prefix='reference-sweep-test-') as directory:
            folder=Path(directory);called=[]
            args=SimpleNamespace(frequency_hz=2400000000,sweep_end_hz=2404000000,
                sweep_step_hz=2000000,output=folder/'sweep.json',data_dir=folder/'raw')
            def point(options):
                called.append(options.frequency_hz)
                if len(called)==2 and scenario=='exception':raise RuntimeError('fake device error')
                result=dict(status='reference_verified',all_tx_processes_ended=True,
                    captures=dict(off=dict(device_drained=True)))
                if len(called)==2:
                    if scenario=='missing-reference':result['status']='reference_not_identified'
                    if scenario=='transport-failed':result['status']='failed'
                    if scenario=='undrained':result['captures']['off']['device_drained']=False
                    if scenario=='tx-unconfirmed':result['all_tx_processes_ended']=False
                return result
            with patch('rf_reference.run',point):result=run_sweep(args)
            complete=scenario in ('complete','missing-reference')
            assert len(called)==(3 if complete else 2)
            assert result['status']==('sweep_completed' if complete else 'blocked')
            assert result['physical_receive_interval_hz'] is None
            assert json.loads(args.output.read_text())==result
            assert args.frequency_hz==2400000000
            cases.append(dict(scenario=scenario,points_called=len(called),status=result['status']))
    return cases


def check_fem_workflow():
    """Mock hardware boundaries while executing the real orchestration."""
    cases=[]
    for scenario in ('standard','success','unsupported','undrained','restore-failure','baseline-trace-mismatch','tx-exit-unconfirmed'):
        with tempfile.TemporaryDirectory(dir=ROOT/'work',prefix='fem-reference-test-') as directory:
            folder=Path(directory);mode=[0];selections=[];received=[];children=[]
            def control(args):
                selections.append(args.value)
                if scenario=='unsupported':return dict(status='failed')
                before=dict(mode=mode[0],epoch=len(received))
                if args.value is not None:
                    if scenario=='restore-failure' and args.output.stem.endswith('-restore'):
                        return dict(status='failed')
                    mode[0]={'default':0,'2':1,'5':2}[args.value]
                return dict(status='passed',before=before,after=dict(mode=mode[0],epoch=len(received)))
            def receive(args,**kwargs):
                received.append((args.output.stem,mode[0]))
                fail=scenario=='undrained' and args.output.stem.endswith('-fem2-tone150')
                return dict(transport_completed=not fail,host=dict(device_drained=not fail,epoch=len(received)))
            class Child:
                def __init__(self,*args,**kwargs):
                    self.returncode=None;self.pid=123;self.actions=[];children.append(self)
                    kwargs['stdout'].write('Press Ctrl + C\n');kwargs['stdout'].flush()
                def poll(self):return self.returncode
                def wait(self,timeout):self.actions.append('wait');self.returncode=0;return 0
                def terminate(self):self.actions.append('terminate');self.returncode=-1
                def kill(self):self.actions.append('kill');self.returncode=-1
            build=folder/'cp-build.json'
            build.write_text(json.dumps(dict(experimental_fem_override=True,rf_status_trace=dict(enabled=True,abi=5))))
            config=SimpleNamespace(port='MOCK',band=5,frequency_hz=881500000,gain_index=40,
                bandwidth_index=0,output=folder/'report.json',data_dir=folder/'data',
                serial='MOCK',tx_gain=0,fem_compare=None if scenario=='standard' else '2',dma_block_bytes=8192,rf_status_cp_build=build)
            def fake_spectrum(*args,**kwargs):return dict(target_power=1.,peak_hz=150000)
            def fake_assess(*args):return dict(status='reference_verified',reference_identified=True)
            def cleanup(child,grace_seconds=0):
                if scenario=='tx-exit-unconfirmed':
                    return dict(process_ended=False,exit_code=None,cleanup_errors=['mock unconfirmed exit'])
                return finish_transmitter(child,grace_seconds)
            with patch('sdr.fem_override.configure',control),patch('rf_reference.receive',receive),\
                 patch('rf_reference.spectrum',fake_spectrum),patch('rf_reference.assess',fake_assess),\
                 patch('sdr.rf_status.snapshot',return_value=dict(status='failed' if scenario=='baseline-trace-mismatch' else 'passed')),\
                 patch('rf_reference.finish_transmitter',cleanup),\
                 patch('rf_reference.subprocess.Popen',Child):
                report=run(config)
            assert all(c.poll() is not None for c in children)
            if scenario=='standard':
                assert report['status']=='reference_verified' and not selections
                assert len(received)==4 and len(children)==2 and 'fem_comparison' not in report
            elif scenario=='success':
                assert report['status']=='reference_verified' and mode[0]==0
                assert report['fem_comparison']['restored_default'] and len(received)==8
                assert [m for _,m in received]==[0,1,0,1,0,1,0,1]
                assert selections[-1]=='default' and len(children)==2
            elif scenario=='unsupported':
                assert not received and not children and selections==[None]
                assert not report['fem_comparison']['restored_default']
            elif scenario=='baseline-trace-mismatch':
                assert report['status']=='failed' and len(received)==1 and not children
                assert selections==[None] and mode[0]==0
            elif scenario=='tx-exit-unconfirmed':
                assert report['status']=='failed' and not report['all_tx_processes_ended']
                assert len(children)==1 and len(received)==6
                assert 'exit unconfirmed' in report['error'] and selections[-1]=='default'
            else:
                assert report['status']=='failed' and not report['fem_comparison']['restored_default']
                assert 'restore_error' in report['fem_comparison']
                if scenario=='undrained':assert selections[-1]=='2' and len(children)==1
                else:assert selections[-1]=='default' and len(children)==2
            if scenario=='undrained':assert children[0].actions==['wait']
            cases.append(dict(scenario=scenario,status=report['status'],captures=len(received),
                finite_tx_children_ended=all(c.poll() is not None for c in children)))
    return cases


def main():
    assert fem_configurations(5,881500000,'2')['tone150']==[
        ('tone150',881500000,150000,5),('fem2-tone150',881500000,150000,5),
        ('rx-plus100',881600000,50000,5),('fem2-rx-plus100',881600000,50000,5)]
    workflow_cases=check_fem_workflow()
    b3_cases=check_b3_candidate()
    sweep_cases=check_sweep()
    configurations=reference_configurations([5,8],900000000)
    assert configurations['tone150']==[
        ('tone150',900000000,150000,5),('route8-tone150',900000000,150000,8),
        ('rx-plus100',900100000,50000,5),('route8-rx-plus100',900100000,50000,8)]
    assert configurations['tone350']==[
        ('tone350',900000000,350000,5),('route8-tone350',900000000,350000,8)]
    assert route_label(5,5,'off')=='off' and route_label(8,5,'off')=='route8-off'
    assert len(reference_configurations([5],900000000)['tone150'])==2
    result=dict(epoch=7,after=dict(state=3,dma_idle=True,error=0),source_recovery=dict(observed_gap_total_ms=12))
    assert capture_terminal(result,True)==dict(epoch=7,device_drained=True,observed_gap_ms=12)
    assert not capture_terminal(dict(result,after=dict(state=1,dma_idle=True,error=0)),True)['device_drained']
    assert not capture_terminal(dict(result,after=dict(state=3,dma_idle=False,error=0)),True)['device_drained']
    assert capture_terminal(dict(host=dict(epoch=8,device_drained=True),observed_gap_ms=0))['device_drained']
    data=ROOT/'work/rf-reference-analysis-test'
    data.mkdir(exist_ok=True)
    rate=1920000
    t=np.arange(int(rate*.4))/rate
    rng=np.random.default_rng(3910)
    captures={}
    for name,tone in (('off',None),('tone150',157500),('rx-plus100',57500),('tone350',357500)):
        # A large unrelated carrier must not masquerade as the requested tone.
        z=100*np.exp(2j*np.pi*700000*t)+rng.normal(0,5,len(t))+1j*rng.normal(0,5,len(t))
        if tone is not None:z+=15*np.exp(2j*np.pi*tone*t)
        pairs=np.column_stack((np.round(z.real),-np.round(z.imag))).astype('<i2')*16
        path=data/(name+'.raw');pairs.tofile(path)
        expected=50000 if name=='rx-plus100' else 350000 if name=='tone350' else 150000
        captures[name]=dict(raw_path=str(path),spectrum=spectrum(path,expected,rate))
    result=assess(captures,rate)
    assert result['reference_identified'],result
    assert all(result['verification_checks'].values()) and not result['failed_checks']
    assert abs(result['retune_shift_hz']-100000)<500
    assert abs(result['tone_separation_hz']-200000)<500
    assert all(c['spectrum']['low_nibble_nonzero_fraction']==0 for c in captures.values())
    assert all(c['spectrum']['iq_amplitude']['near_rail_lane_fraction']==0 for c in captures.values())
    # DC removal must not hide a receiver stuck at the ADC rails. These native
    # extremes also catch int16 squaring/abs overflow in level diagnostics.
    rail_path=data/'rails.raw'
    rails=np.tile(np.array([2047*16,-2048*16],dtype='<i2'),(192000,1))
    rails.tofile(rail_path)
    level=spectrum(rail_path,150000,rate)['iq_amplitude']
    assert level['max_abs_lane_native12']==2048 and level['near_rail_lane_fraction']==1
    assert abs(level['lane_rms_native12']-np.sqrt((2047**2+2048**2)/2))<1e-9
    # A short retained wideband burst must be analyzable even when nominal
    # 200ms skipping would exceed the complete file. Keep DMA-block alignment.
    for wide_rate in (15360000,30720000):
        wide_t=np.arange(256000)/wide_rate
        z=100*np.exp(2j*np.pi*150000*wide_t)
        wide_path=data/('short-'+str(wide_rate)+'.raw')
        (np.column_stack((np.round(z.real),-np.round(z.imag))).astype('<i2')*16).tofile(wide_path)
        measured=spectrum(wide_path,150000,wide_rate)
        assert abs(measured['peak_hz']-150000)<4000 and measured['analysis_skip_complex_samples']%2000==0
        assert measured['analysis_complex_samples']==192000
    # A pre-existing tone in the TX-off capture must fail the on/off evidence.
    # New8192-byte geometry: independently phased DMA blocks model lossy
    # scratch output without allowing an FFT window to straddle a gap.
    dma_samples=2048
    gapped={}
    wide_rate=30720000
    for name,tone in (('off',None),('tone150',150000),('rx-plus100',50000),('tone350',350000)):
        n=np.arange(dma_samples)/wide_rate
        z=rng.normal(0,2,(128,dma_samples))+1j*rng.normal(0,2,(128,dma_samples))
        if tone is not None:
            z+=100*np.exp(2j*np.pi*tone*n+1j*rng.uniform(-np.pi,np.pi,(128,1)))
        path=data/('gapped-'+name+'.raw')
        (np.column_stack((np.round(z.real.ravel()),-np.round(z.imag.ravel()))).astype('<i2')*16).tofile(path)
        expected=50000 if name=='rx-plus100' else 350000 if name=='tone350' else 150000
        measured=spectrum(path,expected,wide_rate,dma_samples=dma_samples)
        assert measured['analysis_skip_complex_samples']%dma_samples==0
        assert measured['analysis_complex_samples']==96*dma_samples
        gapped[name]=dict(raw_path=str(path),spectrum=measured)
    assert assess(gapped,wide_rate)['reference_identified']
    assert all(c['spectrum']['analysis_dma_samples']==2048 for c in gapped.values())
    captures['off']['raw_path']=captures['tone150']['raw_path']
    rejected=assess(captures,rate)
    assert not rejected['reference_identified'] and rejected['sample_rate_from_two_tone_spacing_hz'] is None
    assert rejected['failed_checks']==['reference_on_off'],rejected
    class Child:
        def __init__(self,stuck=False):self.returncode=None;self.actions=[];self.stuck=stuck
        def poll(self):return self.returncode
        def terminate(self):self.actions.append('terminate')
        def kill(self):
            self.actions.append('kill')
            if not self.stuck:self.returncode=-1
        def wait(self,timeout):
            if self.returncode is None:raise subprocess.TimeoutExpired('fake TX child',timeout)
            return self.returncode
    child=Child();cleanup=finish_transmitter(child)
    assert cleanup['process_ended'] and child.actions==['terminate','kill']
    child=Child(stuck=True);cleanup=finish_transmitter(child)
    assert not cleanup['process_ended'] and len(cleanup['cleanup_errors'])==2
    child=Child();child.returncode=0
    assert finish_transmitter(child)['process_ended'] and not child.actions
    class FiniteChild(Child):
        def __init__(self):super().__init__();self.waits=[]
        def wait(self,timeout):
            self.waits.append(timeout)
            if len(self.waits)==1:raise subprocess.TimeoutExpired('finite child',timeout)
            self.returncode=0;return 0
    child=FiniteChild();cleanup=finish_transmitter(child,grace_seconds=3)
    assert cleanup['process_ended'] and not cleanup['forced_shutdown'] and not child.actions
    assert len(child.waits)==2 and all(0<t<=1 for t in child.waits)
    report=dict(status='passed',device_accessed=False,hardware_tested=False,
        fem_workflow_mock_cases=workflow_cases,
        b3_candidate_mock_cases=b3_cases,
        sweep_mock_cases=sweep_cases,
        known_tone_and_retune=result,preexisting_tone_rejected=True,
        independent_phase_2048_sample_dma_windows_checked=True,
        native12_level_before_dc_removal_checked=True,
        finite_tx_cleanup_fallback_and_unconfirmed_exit_checked=True,
        finite_tx_grace_uses_bounded_observation_waits=True,
        paired_route_capture_order_and_primary_key_compatibility_checked=True,
        dependencies={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
            for p in ('tools/verify/verify_rf_reference.py','tools/rf_reference.py','tools/rf_unknown_rate.py','tools/sdr/amplitude.py','tools/sdr/receive.py','tools/sdr/rf_catalog.py','tools/sdr/fem_override.py','tools/sdr/artifacts.py','tools/sdr/sample_rate.py','firmware/sdr_receiver/sample_rate.h')})
    (ROOT/'records/rf/coverage-analysis-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
