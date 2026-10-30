"""Finite fixed-RF-tone receive response measurement through the daily library.

Move RX center, keep B210 RF frequency/rate/amplitude unchanged. Raw IQ and
analysis stay separate from USB transport; no firmware changes or resets.
"""
import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

import numpy as np
from rf_reference import finish_transmitter, spectrum, capture_terminal
from rf_unknown_rate import power as normalized_power
from sdr.receive import receive
from sdr.rf_catalog import ROOT, plan_receive
from sdr.sample_rate import nominal_rate


def power(path,offset,rate,dma_samples=2000):
    found=spectrum(path,offset,rate,dma_samples=dma_samples)
    measured=spectrum(path,offset,rate,power_center_hz=found['peak_hz'],dma_samples=dma_samples)
    bins=int(np.count_nonzero(np.abs(np.fft.fftfreq(8192)*rate-found['peak_hz'])<rate/dma_samples*3))
    measured['integrated_bins']=bins
    measured['noise_subtracted_power']=max(0,measured['target_power']-bins*measured['noise_per_bin'])
    measured['tone_identified']=bool(measured['peak_to_local_median_db']>=12 and
        abs(measured['peak_hz']-offset)<12000 and measured['endpoint_fraction']<.001)
    return measured


def experimental_power(path,offset,rate,center=None):
    """Use an independently inferred rate only as an approximate analysis axis."""
    f,p,meta=normalized_power(path);hz=f*rate
    margin=30000+abs(offset)*.003
    search=abs(hz-offset)<margin
    if not np.any(search):raise ValueError('no bins in experimental tone search window')
    i=int(np.argmax(np.where(search,p,-1)))
    peak_hz=float(hz[i]); target_center=peak_hz if center is None else center
    target=abs(hz-target_center)<rate/2000*3
    local=(abs(hz-offset)>margin+rate/2000)&(abs(hz-offset)<margin+rate/2000*4)
    noise=max(float(np.median(p[local])),1e-30)
    target_power=float(p[target].sum());bins=int(target.sum())
    peak_db=float(10*np.log10(max(p[i],1e-30)/noise))
    return dict(**meta,peak_hz=peak_hz,peak_to_local_median_db=peak_db,
        target_power=target_power,noise_per_bin=noise,integrated_bins=bins,
        noise_subtracted_power=max(0,target_power-bins*noise),
        tone_identified=bool(peak_db>=12 and abs(peak_hz-offset)<margin and meta['endpoint_fraction']<.001),
        estimated_axis_rate_hz=rate,search_margin_hz=margin,sample_rate_calibrated=False)


def summarize(points):
    if len(points)<3 or points[0]['offset_hz']!=150000 or points[-1]['offset_hz']!=150000:
        raise ValueError('response requires start/end+150kHz references')
    for reference in (points[0],points[-1]):
        if not reference['spectrum']['tone_identified'] or reference['spectrum']['noise_subtracted_power']<=0:
            raise ValueError('response reference not identified')
    reference=points[0]['spectrum']['noise_subtracted_power']
    for point in points:
        value=point['spectrum']['noise_subtracted_power']
        point['relative_db']=10*math.log10(value/reference) if point['spectrum']['tone_identified'] and value>0 else None
    drift=points[-1]['relative_db']
    stable=abs(drift)<=1.0
    brackets={}
    for sign,label in ((-1,'negative'),(1,'positive')):
        ordered=sorted((p for p in points[:-1] if sign*p['offset_hz']>0),key=lambda p:abs(p['offset_hz']))
        previous=None;edge=None;rebound=False
        for point in ordered:
            level=point['relative_db']
            if level is None:continue
            if edge and level>=-3:rebound=True
            if previous is not None and previous['relative_db']>=-3 and level<-3 and edge is None:
                edge=[abs(previous['offset_hz']),abs(point['offset_hz'])]
            previous=point
        brackets[label]=dict(offset_magnitude_bracket_hz=edge if stable and not rebound else None,
            nonmonotonic_after_crossing=rebound,reference_drift_passed=stable)
    edges=[brackets[label]['offset_magnitude_bracket_hz'] for label in ('negative','positive')]
    width=[sum(edge[i] for edge in edges) for i in (0,1)] if all(edges) else None
    return dict(status='response_measured' if stable else 'reference_drift_exceeded',
        reference_repeat_drift_db=drift,reference_drift_limit_db=1.0,
        relative_minus3db_edges=brackets,total_minus3db_width_bracket_hz=width,
        scope='sparse fixed-RF-tone end-to-end relative response; includes RX tuning/calibration/analog/DFE path, not calibrated filter specification or every intermediate frequency')


def run(args):
    dma_bytes=getattr(args,'dma_block_bytes',8000)
    request_bytes=getattr(args,'request_bytes',65536)
    if dma_bytes not in (8000,8192) or not 512<=request_bytes<=4*1024*1024 or request_bytes%512:
        raise ValueError('choose supported DMA analysis geometry and aligned USB read length')
    if args.bandwidth_index>=2 and args.offsets_hz is None:
        raise ValueError('wideband response requires explicit targeted offsets; BW1 edge defaults do not apply')
    # These targeted edge points come from previous positive/negative response
    # evidence, not a frequency-range sweep or an assumed BW index mapping.
    offsets=([150000,-150000,-450000,-500000,-550000,-600000,-650000,
        450000,500000,550000,600000,650000,150000] if args.bandwidth_index==0 else
        [150000,-150000,-1200000,-1250000,-1300000,-1350000,-1400000,
        1200000,1250000,1300000,1350000,1400000,150000])
    if args.offsets_hz is not None:
        if not 1<=len(args.offsets_hz)<=18:raise ValueError('choose1..18 targeted offsets')
        offsets=[150000]+args.offsets_hz+[150000]
    selector=getattr(args,'experimental_pre_selector',None)
    if selector is not None and dma_bytes!=8000:
        raise ValueError('legacy experimental rate analyzer requires8000B geometry')
    reference_path=getattr(args,'rate_reference',None)
    if selector is not None:
        if args.bandwidth_index!=5 or reference_path is None:
            raise ValueError('experimental mode requires RF mode5 and a verified independent rate reference')
        rate_record=json.loads(reference_path.read_text(encoding='utf8'))
        if (not rate_record.get('reference_identified') or rate_record.get('experimental_pre_selector')!=selector or
            rate_record.get('band')!=args.band or rate_record.get('center_hz')!=args.center_hz or
            rate_record.get('gain_index')!=args.gain_index):
            raise ValueError('rate reference does not match this experimental RF configuration')
        rate=rate_record.get('sample_rate_from_two_tone_spacing_hz')
        if not isinstance(rate,(int,float)) or not math.isfinite(rate) or rate<=0:
            raise ValueError('experimental rate estimate is unavailable')
    else:
        if reference_path is not None:raise ValueError('rate reference applies only to experimental mode')
        rate=nominal_rate(args.bandwidth_index)
    if any(abs(offset)<50000 or abs(offset)>=rate/2-60000 for offset in offsets):
        raise ValueError('offset must avoid DC and retain spectrum-analysis margin below Nyquist')
    # B210 carrier is center+150kHz throughout; no TX retune or gain changes.
    rf=args.center_hz+150000
    for offset in offsets:plan_receive(args.band,frequency_hz=rf-offset,gain_index=args.gain_index)
    report_path=args.output.resolve();data=args.data_dir.resolve()
    if not report_path.is_relative_to(ROOT) or report_path.exists() or not report_path.parent.is_dir():
        raise ValueError('choose a new project report in an existing directory')
    if not data.is_relative_to(ROOT/'work'):raise ValueError('raw data directory must be under work')
    data.mkdir(parents=True,exist_ok=True)
    prefix=report_path.stem
    labels=['off']+['point'+str(i) for i in range(len(offsets))]
    log=report_path.with_name(prefix+'-tx.log')
    if log.exists() or any((data/(prefix+'-'+label+'.raw')).exists() or
        report_path.with_name(prefix+'-'+label+'.json').exists() for label in labels):
        raise ValueError('response output paths already exist')
    report=dict(status='starting',recorded_at=datetime.now().astimezone().isoformat(),
        band=args.band,bandwidth_index=args.bandwidth_index,gain_index=args.gain_index,
        sample_rate_nominal_hz=None if selector is not None else rate,
        sample_rate_analysis_estimate_hz=rate if selector is not None else None,
        experimental_pre_selector=selector,sample_clock_calibrated=False,RF_signal_hz=rf,
        fixed_TX_center_hz=args.center_hz,fixed_TX_tone_hz=150000,TX_gain_db=args.tx_gain,TX_wave_amplitude=0.3,
        firmware_changed=False,chip_reset=False,points=[],
        setup='Existing antennas; spacing not measured by software. B210 TRX1 intended via established A:A A:B/channel0/TX-RX mapping; physical connector not sensed.',
        calibrated_RF_power=False,calibrated_passband=False)
    report.update(analysis_dma_block_bytes=dma_bytes,usb_request_bytes=request_bytes)
    def save():report_path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    def capture(label,offset):
        center=rf-offset
        options=SimpleNamespace(port=args.port,band=args.band,frequency_hz=center,gain_index=args.gain_index,
            bandwidth_index=args.bandwidth_index,milliseconds=1000,requests=32,request_bytes=request_bytes,
            file_queue_blocks=32,sync_file=False,iq_output=data/(prefix+'-'+label+'.raw'),
            output=report_path.with_name(prefix+'-'+label+'.json'))
        if selector is None:result=receive(options)
        else:
            import sys
            sys.path.insert(0,str(ROOT/'tools/usb'))
            from benchmark import run as raw_benchmark
            options.source='bw0';options.block_bytes=8000;options.slots=7;options.raw_io=False
            options.receiver=ROOT/'outputs/host/windows/sdr_receive.exe';options.experimental_pre_selector=selector
            result=raw_benchmark(options);options.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
        if not result.get('transport_completed'):
            raise RuntimeError('receiver transport failed: '+str(options.output)+'; '+str(result.get('host_stderr',result.get('error','unknown'))))
        terminal=capture_terminal(result,selector is not None)
        if not terminal['device_drained']:raise RuntimeError('receiver did not prove drain: '+str(options.output))
        item=dict(offset_hz=offset,RX_center_hz=center,record=options.output.relative_to(ROOT).as_posix(),
            raw_path=str(options.iq_output),epoch=terminal['epoch'],observed_gap_ms=terminal['observed_gap_ms'],
            spectrum=experimental_power(options.iq_output,offset,rate) if selector is not None else power(options.iq_output,offset,rate,dma_bytes//4))
        print(json.dumps(dict(label=label,offset_hz=offset,peak_db=item['spectrum']['peak_to_local_median_db'],
            peak_hz=item['spectrum']['peak_hz'])),flush=True)
        return item
    process=None;save()
    try:
        report['off']=capture('off',150000);save()
        seconds=math.ceil(len(offsets)*1.6+4)
        command=['C:/Program Files/UHD/lib/uhd/examples/tx_waveforms.exe',
            '--args','type=b200,serial='+args.serial,'--subdev','A:A A:B','--channels','0','--ant','TX/RX',
            '--rate','1000000','--freq',str(args.center_hz),'--gain',str(args.tx_gain),
            '--wave-type','SINE','--wave-freq','150000','--wave-ampl','0.3','--nsamps',str(seconds*1000000)]
        env=dict(os.environ);env['PATH']='C:/Program Files/UHD/bin;'+env.get('PATH','')
        report['TX']=dict(command=command,finite_seconds=seconds,process_ended=False,log=log.relative_to(ROOT).as_posix());save()
        with log.open('x') as stream:
            process=subprocess.Popen(command,env=env,stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            report['TX']['pid']=process.pid;save()
            try:
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    if 'Press Ctrl + C' in log.read_text(errors='replace'):break
                    if process.poll() is not None:raise RuntimeError('TX exited before streaming: '+str(log))
                    time.sleep(.1)
                else:raise TimeoutError('TX did not become ready')
                for index,offset in enumerate(offsets):
                    if process.poll() is not None:raise RuntimeError('finite TX ended before capture')
                    report['points'].append(capture('point'+str(index),offset));save()
                    if process.poll() is not None:raise RuntimeError('finite TX ended during capture')
                process.wait(timeout=seconds+10)
                if process.returncode:raise RuntimeError('TX returned error')
            finally:
                report['TX'].update(finish_transmitter(process));save()
        first=report['points'][0]['spectrum']
        off=(experimental_power(Path(report['off']['raw_path']),150000,rate,center=first['peak_hz'])
            if selector is not None else spectrum(Path(report['off']['raw_path']),150000,rate,power_center_hz=first['peak_hz'],dma_samples=dma_bytes//4))
        report['reference_on_off_db']=10*math.log10(max(first['target_power'],1e-30)/max(off['target_power'],1e-30))
        if report['reference_on_off_db']<10:raise ValueError('reference TX-on/off contrast insufficient')
        report.update(summarize(report['points']))
    except Exception as error:report.update(status='failed',error=str(error))
    report['all_TX_ended']=process is None or process.poll() is not None
    report['dependencies']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
        'tools/rf_response.py','tools/rf_reference.py','tools/sdr/receive.py','tools/sdr/sample_rate.py','firmware/sdr_receiver/sample_rate.h',
        'outputs/host/windows/sdr_receive.exe','outputs/host/windows/sdr_usb.dll')}
    if selector is not None:
        for path in (reference_path.resolve(),ROOT/'tools/rf_unknown_rate.py',ROOT/'tools/usb/benchmark.py'):
            report['dependencies'][path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    report['finished_at']=datetime.now().astimezone().isoformat();save()
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',required=True)
    parser.add_argument('--band',type=int,default=5)
    parser.add_argument('--center-hz',type=int,default=881500000)
    parser.add_argument('--gain-index',type=int,default=30,help='uncalibrated RX index; default30, lower further for overload comparisons')
    parser.add_argument('--bandwidth-index',type=int,choices=(0,1,2,3,4,5),required=True)
    parser.add_argument('--dma-block-bytes',type=int,choices=(8000,8192),default=8000,
                        help='matching firmware DMA geometry for analysis only')
    parser.add_argument('--request-bytes',type=int,default=65536,help='host USB read length, independent of DMA/FFT window')
    parser.add_argument('--experimental-pre-selector',type=int,choices=(5,6,7))
    parser.add_argument('--rate-reference',type=Path,help='verified two-tone estimate for experimental selector only')
    parser.add_argument('--tx-gain',type=float,default=20)
    parser.add_argument('--serial',required=True,help='B210 serial from the current UHD device query')
    parser.add_argument('--offsets-hz',type=int,nargs='+',help='targeted edge refinement; start/end+150kHz references are added')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-dir',type=Path,required=True)
    args=parser.parse_args();report=run(args)
    print(json.dumps({k:v for k,v in report.items() if k not in ('points','dependencies','off')},indent=2))
    return 0 if report['status']=='response_measured' else 1


if __name__=='__main__':raise SystemExit(main())
