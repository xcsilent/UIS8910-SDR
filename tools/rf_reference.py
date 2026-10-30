"""One finite B210 RF reference comparison through the normal SDR receiver.

TX-off, two tone offsets and a100kHz RX retune; no firmware writes or resets.
Raw IQ and analysis are separate from the transport implementation.
"""
import argparse
import copy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

import numpy as np
from sdr.receive import receive
from sdr.rf_catalog import ROOT, plan_receive
from sdr.sample_rate import nominal_rate
import rf_unknown_rate
from sdr.artifacts import recorded_file
from sdr.amplitude import native12_amplitude

class ReferenceMissing(RuntimeError):
    pass


def capture_terminal(result,experimental=False):
    if experimental:
        terminal=result.get('after',{})
        return dict(epoch=result.get('epoch'),
            observed_gap_ms=result.get('source_recovery',{}).get('observed_gap_total_ms'),
            device_drained=bool(terminal.get('state')==3 and terminal.get('dma_idle') and not terminal.get('error')))
    terminal=result.get('host',{})
    return dict(epoch=terminal.get('epoch'),observed_gap_ms=result.get('observed_gap_ms'),
                device_drained=terminal.get('device_drained'))


def spectrum(path, expected_hz, sample_rate, *, power_center_hz=None, dma_samples=2000):
    path = recorded_file(path)
    # Skip nominal200ms, then average96 DMA-aligned Hann windows. Zero-padding
    # improves peak interpolation only, not physical spectral resolution.
    # Gapped wideband raw may contain fewer samples than200ms at nominal Fs.
    # Keep the supplied DMA-window alignment and use a retained tail when needed;
    # sample offset is not a known wall-clock settling time across source gaps.
    if dma_samples not in (2000,2048):
        raise ValueError('supported DMA window sizes are 2000 or 2048 complex samples')
    available=Path(path).stat().st_size//4
    skip=min(int(sample_rate*.2)//dma_samples*dma_samples,max(0,(available-dma_samples*96)//dma_samples*dma_samples))
    words = np.fromfile(path, dtype='<u4', count=dma_samples*96, offset=skip*4)
    if len(words) != dma_samples*96:
        raise ValueError('capture too short for reference analysis')
    a = (words & 65535).astype('<u2').view('<i2').astype(np.int32) >> 4
    b = (words >> 16).astype('<u2').view('<i2').astype(np.int32) >> 4
    z = (a-1j*b).reshape(-1,dma_samples)
    z -= z.mean(axis=1)[:,None]
    power = np.mean(np.abs(np.fft.fft(z*np.hanning(dma_samples), n=8192, axis=1))**2, axis=0)
    freq = np.fft.fftfreq(8192)*sample_rate
    search = np.abs(freq-expected_hz) < 15000
    peak = int(np.argmax(np.where(search,power,-1)))
    # Fixed search-band integration keeps TX-on/off power comparisons on the
    # same bins, including the small uncalibrated carrier offset.
    target = search if power_center_hz is None else np.abs(freq-power_center_hz)<sample_rate/dma_samples*3
    local = (np.abs(freq-expected_hz)>20000) & (np.abs(freq-expected_hz)<60000)
    noise = max(float(np.median(power[local])), 1e-30)
    return dict(expected_offset_hz=expected_hz, peak_hz=float(freq[peak]),
        analysis_skip_complex_samples=skip,analysis_complex_samples=len(words),
        analysis_dma_samples=dma_samples,analysis_window_crosses_dma_boundary=False,
        alignment_scope='Requires raw starting at a DMA boundary and no partial-block deletion; not a continuity claim',
        analysis_wall_clock_settling_known=False,
        peak_to_local_median_db=float(10*np.log10(max(power[peak],1e-30)/noise)),
        target_power=float(np.sum(power[target])), noise_per_bin=noise,
        power_band_center_hz=expected_hz if power_center_hz is None else power_center_hz,
        power_band_halfwidth_hz=15000 if power_center_hz is None else sample_rate/dma_samples*3,
        endpoint_fraction=float(np.mean((a<=-2048)|(a>=2047)|(b<=-2048)|(b>=2047))),
        iq_amplitude=native12_amplitude(a,b),
        low_nibble_nonzero_fraction=float(np.mean((words & 0x000f000f)!=0)),
        sample_rate_nominal_hz=sample_rate, sample_rate_calibrated=False,
        interpretation='lane0-j*lane1; physical I/Q labels and absolute phase unknown')


def assess(captures, sample_rate):
    spectra = {k:v['spectrum'] for k,v in captures.items()}
    on, shifted, second = (spectra[k] for k in ('tone150','rx-plus100','tone350'))
    # Compare equal narrow bins around the observed TX-on peak. A wide noise
    # integration can hide a clearly identified tone in a busy RF environment.
    for name in ('off','tone150'):
        spectra[name] = spectrum(Path(captures[name]['raw_path']),150000,sample_rate,
            power_center_hz=on['peak_hz'],dma_samples=spectra[name].get('analysis_dma_samples',2000))
        captures[name]['spectrum'] = spectra[name]
    delta = second['peak_hz']-on['peak_hz']
    retune = on['peak_hz']-shifted['peak_hz']
    on_off_db = float(10*np.log10(max(spectra['tone150']['target_power'],1e-30)/max(spectra['off']['target_power'],1e-30)))
    checks = dict(
        tone_prominence=all(s['peak_to_local_median_db']>=12 for s in (on,shifted,second)),
        expected_offsets=all(abs(s['peak_hz']-s['expected_offset_hz'])<12000 for s in (on,shifted,second)),
        reference_on_off=on_off_db>=10,
        tone_separation=abs(delta-200000)<4000,
        retune_following=abs(retune-100000)<4000)
    verified = all(checks.values())
    return dict(status='reference_verified' if verified else 'reference_not_identified',
        reference_identified=bool(verified),verification_checks=checks,
        failed_checks=[name for name,passed in checks.items() if not passed],
        tone_separation_hz=delta,retune_shift_hz=retune,
        tone150_vs_off_db=on_off_db,
        sample_rate_from_two_tone_spacing_hz=sample_rate*200000/delta if verified else None,
        evidence_scope='one RF center plus100kHz retune only; no continuous interval or chip limit assertion')


def finish_transmitter(process,grace_seconds=0):
    """Reap only our TX child; preserve receiver errors if shutdown also fails."""
    errors=[]
    forced=False
    # Only a caller with a finite, confirmed streaming child supplies grace.
    # Short observation waits preserve responsiveness; never restart a child.
    deadline=time.monotonic()+max(0,grace_seconds)
    while process.poll() is None and time.monotonic()<deadline:
        try:process.wait(timeout=min(1.,max(.001,deadline-time.monotonic())))
        except subprocess.TimeoutExpired:pass
        except OSError as error:
            errors.append(str(error));break
    if process.poll() is None:
        forced=True
        for operation in ('terminate','kill'):
            try:
                getattr(process,operation)()
                process.wait(timeout=5)
            except (OSError,subprocess.TimeoutExpired) as error:
                errors.append(str(error))
            if process.poll() is not None: break
    return dict(process_ended=process.poll() is not None,exit_code=process.returncode,
        forced_shutdown=forced,grace_budget_seconds=grace_seconds,
        cleanup_errors=errors,finished_at=datetime.now().astimezone().isoformat())


def route_label(band,primary,label):
    return label if band==primary else 'route'+str(band)+'-'+label


def reference_configurations(bands,center):
    """Interleave routes within the same finite TX, preserving primary keys."""
    primary=bands[0]
    return {tone:[(route_label(b,primary,label),hz,offset,b)
        for label,hz,offset in steps for b in bands]
        for tone,steps in (
            ('tone150',[('tone150',center,150000),('rx-plus100',center+100000,50000)]),
            ('tone350',[('tone350',center,350000)]))}


def fem_configurations(band,center,value):
    """Same route, interleaved default/one known switch value in each TX."""
    return {tone:[(prefix+label,hz,offset,band)
        for label,hz,offset,_ in steps for prefix in ('','fem'+value+'-')]
        for tone,steps in reference_configurations([band],center).items()}


def run(args):
    comparison=getattr(args,'comparison_band',None)
    fem_value=getattr(args,'fem_compare',None)
    if fem_value is not None and (fem_value not in ('2','5') or args.band not in (5,8) or
        comparison is not None or getattr(args,'experimental_pre_selector',None) is not None or
        getattr(args,'stop_on_missing_first_tone',False) or args.bandwidth_index!=0):
        raise ValueError('FEM comparison requires one B5/B8 route, BW0, value2/5 and complete reference steps')
    bands=[args.band] if comparison is None else [args.band,comparison]
    if comparison is not None and (comparison==args.band or
        getattr(args,'experimental_pre_selector',None) is not None or
        getattr(args,'stop_on_missing_first_tone',False)):
        raise ValueError('route comparison requires distinct standard routes and all reference steps')
    selected = getattr(args,'receiver_executable',None)
    if selected is not None:
        selected = Path(selected).resolve()
        if not selected.is_relative_to(ROOT) or not selected.is_file() or not selected.with_name('sdr_usb.dll').is_file():
            raise ValueError('receiver and matching sdr_usb.dll must exist inside the project')
        if getattr(args,'experimental_pre_selector',None) is not None:
            raise ValueError('custom receiver is supported only for standard capture')
    for band in bands:
        floor=getattr(args,'experimental_b3_min_hz',None)
        unrestricted=getattr(args,'unrestricted_frequency',False)
        if unrestricted:
            if selected is None or args.rf_status_cp_build is None or floor is not None:
                raise ValueError('unrestricted frequency requires candidate receiver and CP manifest')
            from sdr.receive import verify_experimental_receiver
            verify_experimental_receiver(selected,None,True)
            cp=json.loads(args.rf_status_cp_build.read_text(encoding='utf-8'))
            if not cp.get('unrestricted_frequency'):
                raise ValueError('CP unrestricted frequency setting differs')
        if floor is not None and (band!=3 or selected is None or args.rf_status_cp_build is None):
            raise ValueError('B3 extension requires explicit B3, candidate receiver and matching CP manifest')
        if floor is not None:
            from sdr.receive import verify_experimental_receiver
            verify_experimental_receiver(selected,floor)
            cp=json.loads(args.rf_status_cp_build.read_text(encoding='utf-8'))
            if cp.get('experimental_b3_min_hz')!=floor:
                raise ValueError('B3 extension CP manifest floor differs')
        plan_receive(band,frequency_hz=args.frequency_hz,gain_index=args.gain_index,experimental_b3_min_hz=floor,unrestricted_frequency=unrestricted)
        plan_receive(band,frequency_hz=args.frequency_hz+100000,gain_index=args.gain_index,experimental_b3_min_hz=floor,unrestricted_frequency=unrestricted)
    record = args.output.resolve()
    if not record.is_relative_to(ROOT) or record.exists() or not record.parent.is_dir():
        raise ValueError('choose a new report in an existing project directory')
    data = args.data_dir.resolve()
    data.mkdir(parents=True,exist_ok=True)
    prefix = record.stem
    # Refuse reuse before any hardware operations or partial report overwrite.
    labels = tuple(route_label(b,args.band,label) for b in bands
                   for label in ('off','tone150','rx-plus100','tone350'))
    if fem_value is not None:
        labels += tuple('fem'+fem_value+'-'+label for label in ('off','tone150','rx-plus100','tone350'))
    paths = [data/(prefix+'-'+label+'.raw') for label in labels]
    paths += [record.with_name(prefix+'-'+label+'.json') for label in labels]
    paths += [record.with_name(prefix+'-'+label+'-tx.log') for label in ('tone150','tone350')]
    if any(p.exists() for p in paths):
        raise ValueError('reference capture paths already exist')
    report = dict(recorded_at=datetime.now().astimezone().isoformat(),status='starting',
        band=args.band,center_hz=args.frequency_hz,gain_index=args.gain_index,
        tx_gain_db=args.tx_gain,tx_wave_amplitude=0.3,
        bandwidth_index=args.bandwidth_index, firmware_changed=False,chip_reset=False,
        setup='Existing antennas; spacing and physical wiring not measured by software.',
        connector='TRX1; established A:A A:B/channel0 mapping; physical wiring not sensed by software',
        captures={},transmissions=[],physical_receive_interval_hz=None)
    if comparison is not None:
        report['route_comparison']=dict(routes=bands,shared_finite_tx_per_tone=True,
            scope='Sequential routes in each same TX burst; uncalibrated antenna/AGC/end-to-end comparison, not sensitivity or physical limit.')
    if fem_value is not None:
        report['fem_comparison']=dict(value=int(fem_value),same_route=True,shared_finite_tx_per_tone=True,
            restored_default=False,scope='Only known slave13/reg0 switch-open byte differs; no chip identity, calibrated sensitivity or continuous coverage claim.')
    trace_build=getattr(args,'rf_status_cp_build',None)
    snapshot_policy=getattr(args,'rf_snapshot_policy','all')
    if snapshot_policy not in ('all','first'):
        raise ValueError('unknown RF snapshot policy')
    if snapshot_policy=='first' and (comparison is not None or fem_value is not None):
        raise ValueError('route/FEM comparisons require all RF snapshots')
    experimental_selector=getattr(args,'experimental_pre_selector',None)
    if experimental_selector is not None and args.bandwidth_index!=5:
        raise ValueError('experimental selector reference requires RF bandwidth mode5')
    if experimental_selector is not None:
        report['experimental_pre_selector']=experimental_selector
        report['sample_rate_nominal_hz']=None
    tx_subdev=getattr(args,'tx_subdev','A:A A:B')
    report['tx_subdev']=tx_subdev
    report['analysis_dma_block_bytes']=getattr(args,'dma_block_bytes',8000)
    request_bytes=getattr(args,'request_bytes',65536)
    if not 512<=request_bytes<=4*1024*1024 or request_bytes%512:
        raise ValueError('USB request bytes must be a512-byte multiple up to4MiB')
    report['usb_request_bytes']=request_bytes
    report['connector']='TRX1 intended; explicit software subdevice recorded; physical wiring not sensed'
    if trace_build:
        manifest=json.loads(Path(trace_build).read_text(encoding='utf-8'))
        if not manifest.get('rf_status_trace',{}).get('enabled'):
            raise ValueError('explicit opt-in RF status CP build required')
        report['rf_phase_trace_scope']=('post-drain snapshot after each capture' if snapshot_policy=='all'
            else 'post-drain snapshot after first capture only; subsequent transport/drain checks retained')+'; transaction checkpoints, not lock-time or bit-meaning proof'
    if fem_value is not None and (not trace_build or not manifest.get('experimental_fem_override') or
        manifest.get('rf_status_trace',{}).get('abi')!=5):
        raise ValueError('FEM comparison requires explicit matching experimental FEM CP build with trace ABI5')
    sample_rate = nominal_rate(args.bandwidth_index)
    env = dict(os.environ)
    env['PATH'] = 'C:/Program Files/UHD/bin;'+env.get('PATH','')
    transmitter = Path('C:/Program Files/UHD/lib/uhd/examples/tx_waveforms.exe')

    def save():
        record.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')

    fem_mode=None
    fem_dirty=False
    last_drained=False
    fem_step=0
    def select_fem(value,tag):
        nonlocal fem_mode,fem_dirty,fem_step
        from sdr.fem_override import configure
        fem_step+=1
        path=record.with_name(prefix+'-fem-'+str(fem_step)+'-'+tag+'.json')
        if value is not None:fem_dirty=True
        control=configure(SimpleNamespace(port=args.port,value=value,output=path))
        report['fem_comparison'].setdefault('control_records',[]).append(path.relative_to(ROOT).as_posix())
        save()
        if control['status']!='passed':raise RuntimeError('FEM control failed: '+str(path))
        state=control.get('after',control['before'])
        fem_mode={0:'default',1:'2',2:'5'}[state['mode']]
        if value is not None and fem_mode!=value:raise RuntimeError('FEM selection mismatch')
        return state

    def capture(label, center, offset, band):
        nonlocal last_drained
        if fem_value is not None:
            value=fem_value if label.startswith('fem'+fem_value+'-') else 'default'
            if fem_mode!=value:
                if not last_drained:raise RuntimeError('previous receiver not drained; FEM comparison stopped')
                select_fem(value,label)
        config = SimpleNamespace(port=args.port,band=band,frequency_hz=center,
            experimental_b3_min_hz=getattr(args,'experimental_b3_min_hz',None),
            unrestricted_frequency=getattr(args,'unrestricted_frequency',False),
            gain_index=args.gain_index,bandwidth_index=args.bandwidth_index,milliseconds=1000,
            requests=32,request_bytes=request_bytes,file_queue_blocks=32,sync_file=False,
            iq_output=data/(prefix+'-'+label+'.raw'),output=record.with_name(prefix+'-'+label+'.json'))
        last_drained=False
        if experimental_selector is None:result = receive(config, executable=getattr(args,'receiver_executable',None))
        else:
            import sys
            sys.path.insert(0,str(ROOT/'tools/usb'))
            from benchmark import run as raw_benchmark
            config.source='bw0';config.block_bytes=8000;config.slots=7;config.raw_io=False
            config.receiver=ROOT/'outputs/host/windows/sdr_receive.exe'
            config.experimental_pre_selector=experimental_selector
            result=raw_benchmark(config)
            config.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
        report['captures'][label] = dict(record=config.output.relative_to(ROOT).as_posix(),
            requested_band=band,requested_center_hz=center,
            raw_path=str(config.iq_output),transport_completed=result.get('transport_completed',False),
            **capture_terminal(result,experimental_selector is not None))
        last_drained=report['captures'][label]['device_drained'] is True
        if fem_value is not None:report['captures'][label]['fem_mode']=fem_mode
        if not result.get('transport_completed') or not last_drained:
            save()
            raise RuntimeError('native receiver failed: '+str(config.output)+'; '+
                str(result.get('host_stderr',result.get('error','no terminal transport/drain proof'))))
        report['captures'][label]['spectrum'] = (rf_unknown_rate.spectrum(config.iq_output)
            if experimental_selector is not None else spectrum(config.iq_output,offset,sample_rate,
                dma_samples=getattr(args,'dma_block_bytes',8000)//4))
        if trace_build and (snapshot_policy=='all' or len(report['captures'])==1):
            from sdr.rf_status import snapshot
            trace_path=record.with_name(prefix+'-'+label+'-rf-status.json')
            trace=snapshot(args.port,trace_build,trace_path)
            report['captures'][label]['rf_status_record']=trace_path.relative_to(ROOT).as_posix()
            if trace['status']!='passed':raise RuntimeError('RF phase snapshot failed: '+str(trace_path))
        save()
        print(json.dumps(dict(capture=label,**report['captures'][label]['spectrum'])),flush=True)

    def transmit(label, offset, configurations):
        finite_samples = max(4,4+2*len(configurations))*1000000
        if trace_build and snapshot_policy=='all':finite_samples+=len(configurations)*4000000
        command = [str(transmitter),'--args','type=b200,serial='+args.serial,
            '--subdev',tx_subdev,'--channels','0','--ant','TX/RX','--rate','1000000',
            '--freq',str(args.frequency_hz),'--gain',str(args.tx_gain),'--wave-type','SINE',
            '--wave-freq',str(offset),'--wave-ampl','0.3','--nsamps',str(finite_samples)]
        log = record.with_name(prefix+'-'+label+'-tx.log')
        tx = dict(command=command,finite_samples=finite_samples,log=log.relative_to(ROOT).as_posix(),
            capture_order=[dict(label=c[0],center_hz=c[1],expected_hz=c[2],band=c[3]) for c in configurations],
            started_at=datetime.now().astimezone().isoformat(),process_ended=False)
        report['transmissions'].append(tx)
        save()
        with log.open('x') as stream:
            process = subprocess.Popen(command,env=env,stdout=stream,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
            tx['pid']=process.pid
            save()
            streaming_deadline=None
            try:
                deadline = time.monotonic()+30
                while time.monotonic()<deadline:
                    if 'Press Ctrl + C' in log.read_text(errors='replace'):
                        streaming_deadline=time.monotonic()+finite_samples/1000000+5
                        break
                    if process.poll() is not None:
                        raise RuntimeError('TX exited before streaming: '+str(log))
                    time.sleep(.1)
                else: raise TimeoutError('TX readiness timeout: '+str(log))
                for label_rx, center, expected, band in configurations:
                    if process.poll() is not None: raise RuntimeError('finite TX ended before capture')
                    capture(label_rx,center,expected,band)
                    if label_rx=='tone150' and getattr(args,'stop_on_missing_first_tone',False):
                        s=report['captures'][label_rx]['spectrum']
                        if s['peak_to_local_median_db']<12 or (experimental_selector is None and abs(s['peak_hz']-expected)>=12000):
                            raise ReferenceMissing('first reference tone not identified; remaining TX/retune skipped')
                    if process.poll() is not None: raise RuntimeError('finite TX ended during capture')
                # UHD's finite TX duration is derived from nsamps/rate and
                # may exceed the capture window. Allow the declared burst to
                # finish plus a bounded teardown margin.
                process.wait(timeout=finite_samples/1000000+12)
                if process.returncode: raise RuntimeError('TX returned error: '+str(log))
            finally:
                # Also allow a finite UHD burst to release normally on RX,
                # trace or mode-control failure, not only a missing tone.
                grace=max(0,streaming_deadline-time.monotonic()) if streaming_deadline else 0
                tx.update(finish_transmitter(process,grace))
                save()
                if not tx['process_ended']:
                    raise RuntimeError('TX child exit unconfirmed; no further RF experiment: '+str(log))

    save()
    try:
        if fem_value is not None:
            state=select_fem(None,'preflight')
            if state['mode']!=0:raise RuntimeError('FEM comparison requires initial default mode; no capture started')
        for band in bands:
            capture(route_label(band,args.band,'off'),args.frequency_hz,150000,band)
        if fem_value is not None:
            capture('fem'+fem_value+'-off',args.frequency_hz,150000,args.band)
        configurations=(fem_configurations(args.band,args.frequency_hz,fem_value) if fem_value is not None
            else reference_configurations(bands,args.frequency_hz))
        transmit('tone150',150000,configurations['tone150'])
        transmit('tone350',350000,configurations['tone350'])
        report.update(rf_unknown_rate.assess(report['captures']) if experimental_selector is not None else assess(report['captures'],sample_rate))
        if comparison is not None:
            per_route={}
            for band in bands:
                captures={label:report['captures'][route_label(band,args.band,label)]
                          for label in ('off','tone150','rx-plus100','tone350')}
                per_route[str(band)]=assess(captures,sample_rate)
            report['route_comparison']['assessments']=per_route
            report['route_comparison']['all_routes_reference_verified']=all(
                r['reference_identified'] for r in per_route.values())
        if fem_value is not None:
            changed={label:report['captures']['fem'+fem_value+'-'+label]
                for label in ('off','tone150','rx-plus100','tone350')}
            outcome=assess(changed,sample_rate)
            report['fem_comparison']['override_assessment']=outcome
            report['fem_comparison']['default_reference_identified']=report['reference_identified']
            if report['reference_identified'] and outcome['reference_identified']:
                baseline=report['captures']['tone150']['spectrum']
                variant=changed['tone150']['spectrum']
                report['fem_comparison']['override_minus_default_target_power_db']=float(
                    10*np.log10(max(variant['target_power'],1e-30)/max(baseline['target_power'],1e-30)))
    except ReferenceMissing as error:
        report.update(status='reference_not_identified',reference_identified=False,error=str(error))
    except Exception as error:
        report.update(status='failed',error=str(error))
    finally:
        if fem_value is not None:
            try:
                if fem_dirty:
                    if not last_drained:raise RuntimeError('receiver drain not proved; inspect/stop before restoring FEM default')
                    select_fem('default','restore')
                report['fem_comparison']['restored_default']=fem_mode=='default'
            except Exception as error:
                report['fem_comparison']['restore_error']=str(error)
                report['status']='failed'
            save()
    report['all_tx_processes_ended'] = all(t['process_ended'] for t in report['transmissions'])
    executable = Path(getattr(args,'receiver_executable',None) or ROOT/'outputs/host/windows/sdr_receive.exe').resolve()
    host_files = (executable, executable.with_name('sdr_usb.dll'))
    report['dependencies'] = {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in (
        'tools/rf_reference.py','tools/rf_unknown_rate.py','tools/sdr/receive.py','tools/sdr/rf_catalog.py','tools/sdr/sample_rate.py','firmware/sdr_receiver/sample_rate.h',
        )}
    for path in host_files:
        report['dependencies'][path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if trace_build:
        for path in (ROOT/'tools/sdr/rf_status.py',Path(trace_build).resolve()):
            report['dependencies'][path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    if experimental_selector is not None:
        report['dependencies']['tools/usb/benchmark.py']=hashlib.sha256((ROOT/'tools/usb/benchmark.py').read_bytes()).hexdigest()
    if fem_value is not None:
        path=ROOT/'tools/sdr/fem_override.py'
        report['dependencies'][path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    report['finished_at'] = datetime.now().astimezone().isoformat()
    save()
    return report


def run_sweep(args):
    """Bounded grid of complete references; control failures stop the entire grid."""
    end=args.sweep_end_hz; step=args.sweep_step_hz
    if step is None or step<=0 or step%100 or end<args.frequency_hz or (end-args.frequency_hz)%step:
        raise ValueError('sweep requires an inclusive ascending grid in 100 Hz units')
    path=args.output.resolve()
    if not path.is_relative_to(ROOT) or path.exists() or not path.parent.is_dir():
        raise ValueError('choose a new sweep report in an existing project directory')
    frequencies=range(args.frequency_hz,end+1,step)
    # Reserve every point path before the first hardware operation.
    paths=[path.with_name(path.stem+'-'+str(hz)+'.json') for hz in frequencies]
    if any(p.exists() for p in paths):raise ValueError('sweep point report already exists')
    report=dict(status='running',started_at=datetime.now().astimezone().isoformat(),
        first_hz=args.frequency_hz,last_hz=end,step_hz=step,requested_points=len(frequencies),
        points=[],physical_receive_interval_hz=None,
        scope='Complete TX-off/two-tone/retune checks at grid points; gaps between points and chip limits remain unproven.')
    def save():path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    save()
    for hz,point_path in zip(frequencies,paths):
        options=copy.copy(args);options.frequency_hz=hz;options.output=point_path
        options.data_dir=args.data_dir/str(hz)
        try:
            result=run(options)
            report['points'].append(dict(frequency_hz=hz,status=result['status'],
                record=point_path.relative_to(ROOT).as_posix(),
                tone150_vs_off_db=result.get('tone150_vs_off_db'),
                failed_checks=result.get('failed_checks'),error=result.get('error')))
            ended=result.get('all_tx_processes_ended') is True
            drained=all(c.get('device_drained') is True for c in result.get('captures',{}).values())
            if result['status'] not in ('reference_verified','reference_not_identified') or not ended or not drained:
                raise RuntimeError('control/transport/TX cleanup failure at '+str(hz)+'; stop sweep')
        except Exception as error:
            report.update(status='blocked',error=str(error));save();return report
        save()
        print(json.dumps(dict(sweep_point_hz=hz,status=result['status'],
            completed=len(report['points']),total=len(frequencies))),flush=True)
    report.update(status='sweep_completed',finished_at=datetime.now().astimezone().isoformat(),
        verified_points=sum(p['status']=='reference_verified' for p in report['points']))
    save();return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',required=True)
    parser.add_argument('--band',type=int,required=True)
    parser.add_argument('--comparison-band',type=int,help='alternate another supported route under the same finite TX bursts; no experimental PRE or early tone skip')
    parser.add_argument('--fem-compare',choices=('2','5'),help='BW0 same-route B5/B8 default versus known switch-open byte; requires opt-in firmware, restores default after drained captures')
    parser.add_argument('--frequency-hz',type=int,required=True)
    parser.add_argument('--gain-index',type=int,default=30,help='uncalibrated RX index; default30, lower further for overload comparisons')
    parser.add_argument('--bandwidth-index',type=int,choices=(0,1,2,3,4,5),default=0)
    parser.add_argument('--dma-block-bytes',type=int,choices=(8000,8192),default=8000,
                        help='matching firmware DMA block geometry for offline FFT windows; does not configure hardware')
    parser.add_argument('--request-bytes',type=int,default=65536,
                        help='host USB read size;8192 avoids observed partial64KiB tail in v20 short captures at higher CPU cost; independent of DMA/FFT geometry')
    parser.add_argument('--experimental-pre-selector',type=int,choices=(5,6,7),help='infer RF rate without nominal Fs using matching finite experimental firmware')
    parser.add_argument('--serial',required=True,help='B210 serial from the current UHD device query')
    parser.add_argument('--tx-gain',type=float,default=20)
    parser.add_argument('--tx-subdev',default='A:A A:B',help='explicit UHD TX subdevice specification; select from current device identity/mapping')
    parser.add_argument('--stop-on-missing-first-tone',action='store_true',help='skip remaining captures/tones if first tone is missing; let finite TX finish normally')
    parser.add_argument('--rf-status-cp-build',type=Path,help='optional matching diagnostic CP manifest; read phase records after each drained capture')
    parser.add_argument('--rf-snapshot-policy',choices=('all','first'),default='all',help='first retains matching generation/stopped snapshot once per point, without repeated phase snapshots during TX; comparisons require all')
    parser.add_argument('--sweep-end-hz',type=int,help='inclusive end of a bounded grid of complete reference experiments')
    parser.add_argument('--sweep-step-hz',type=int,help='grid step; requires --sweep-end-hz')
    parser.add_argument('--receiver-executable',type=Path,help='matching Windows receiver build for a firmware candidate')
    parser.add_argument('--experimental-b3-min-hz',type=int,help='explicit manual B3 floor, matching candidate host and CP manifests required')
    parser.add_argument('--unrestricted-frequency',action='store_true',help='manual route without band envelope; matching candidate host/CP required')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-dir',type=Path,required=True)
    args = parser.parse_args()
    if args.sweep_end_hz is None and args.sweep_step_hz is not None:parser.error('--sweep-step-hz requires --sweep-end-hz')
    result = run_sweep(args) if args.sweep_end_hz is not None else run(args)
    print(json.dumps({k:v for k,v in result.items() if k not in ('captures','dependencies')},indent=2))
    return 0 if result['status'] in ('reference_verified','sweep_completed') else 1


if __name__ == '__main__': raise SystemExit(main())
