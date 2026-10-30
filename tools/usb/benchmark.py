"""Run a finite fixed-buffer or BW0 raw Bulk capture after manual flashing.

Control uses COM monitor; payload is read by the native asynchronous WinUSB
receiver. BW0 uses the service configuration/start/stop control interface.
No IQ parsing, payload CRC or USB driver rebinding.
"""
import argparse
import ctypes
from datetime import datetime
import json
from pathlib import Path
import queue
import struct
import subprocess
import sys
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[2]
from native_control import ControlClient


def validate_source_capabilities(info,source):
    """Use only the known ABI explicitly advertised by this running image.

    A BW0 image retains the fixed-source diagnostic, but its different name
    used to make that diagnostic unreachable from the host entry point.
    """
    if source not in ('fixed','bw0'):
        raise ValueError('unknown raw USB data source')
    if (info.get('firmware') not in ('uis8910-sdr-raw-usb-v1','uis8910-sdr-bw0-usb-v1') or
            info.get('raw_usb') is not True or info.get('raw_usb_abi')!=1 or
            info.get('raw_usb_source')!='fixed_ap_buffer_benchmark' or
            any(info.get(key)!=value for key,value in (
                ('raw_usb_status_operation',40),('raw_usb_start_operation',41),('raw_usb_stop_operation',42)))):
        raise ValueError('running firmware does not advertise the supported raw USB ABI; no start command sent')
    if info.get('firmware')=='uis8910-sdr-bw0-usb-v1' and (
            info.get('bw0_usb') is not True or info.get('bw0_status_operation')!=44):
        raise ValueError('BW0 ownership status is unavailable; no start command sent')
    if source=='bw0' and (info.get('firmware')!='uis8910-sdr-bw0-usb-v1' or
            info.get('bw0_usb') is not True or any(info.get(key)!=value for key,value in (
                ('bw0_status_operation',44),('bw0_start_operation',45),
                ('bw0_stop_operation',46),('bw0_config_operation',47)))):
        raise ValueError('running firmware does not advertise the supported BW0 controls; no start command sent')


def validate_experimental_profile(info,selector):
    if selector is None:return 0
    advertised=info.get('bw0_experimental_pre_selectors')
    matches=(advertised==[5,6,7] and selector in advertised) if advertised is not None else info.get('bw0_experimental_pre_selector')==selector
    if (selector not in (5,6,7) or not matches or
            info.get('bw0_experimental_rf_mode')!=5 or info.get('bw0_experimental_rate_known') is not False or
            5 not in info.get('bw0_bandwidth_indices',[]) or info.get('bw0_config_abi')!=2 or
            info.get('bw0_until_stop')):
        raise ValueError('matching finite unknown-rate PRE experiment is not advertised; no CONFIG or START sent')
    return selector if advertised is not None else 5


def check_fixed_source_ownership(client,info):
    """Only read BW0 ownership. Never release or reset its retained CP context."""
    if info.get('bw0_usb'):
        value=status(client,'bw0')
        if value['cp_held'] or value['state'] in (1,2):
            raise ValueError('BW0 owns the CP service; fixed-source control is excluded. '
                             'Use the BW0 path; no start, stop or reset command sent.')
        return value
    return None


class StopEvent:
    """One named Windows event per receiver process; no payload/control framing."""
    def __enter__(self):
        from ctypes import wintypes
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        self.api.CreateEventW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.BOOL,wintypes.LPCWSTR]
        self.api.CreateEventW.restype=wintypes.HANDLE
        self.api.SetEvent.argtypes=[wintypes.HANDLE]
        self.api.SetEvent.restype=wintypes.BOOL
        self.api.CloseHandle.argtypes=[wintypes.HANDLE]
        self.api.CloseHandle.restype=wintypes.BOOL
        self.name='Local\\UIS8910-SDR-'+uuid.uuid4().hex
        self.handle=self.api.CreateEventW(None,True,False,self.name)
        if not self.handle: raise ctypes.WinError(ctypes.get_last_error())
        return self

    def signal(self):
        if not self.api.SetEvent(self.handle): raise ctypes.WinError(ctypes.get_last_error())

    def __exit__(self,*exception):
        self.api.CloseHandle(self.handle)


def status(client,source='fixed',with_recovery=False):
    if source=='bw0':
        data=client.request(44)
        if len(data)!=192: raise ValueError('BW0 USB status size differs')
        w=struct.unpack('<48I',data)
        if w[:2]!=(0x31574353,1): raise ValueError('BW0 USB status ABI differs')
        result=dict(magic=w[0],abi=w[1],install_status=w[41] if w[2] else 10,
            interface=w[42],pipe=w[43],enabled=w[44],state={0:0,1:1,2:1,3:1,4:3,5:4}.get(w[3],4),
            error=w[4],epoch=w[5],duration_ms=w[6],elapsed_ms=w[46],total_elapsed_ms=w[7],
            source=w[8],sample_rate_nominal_hz=w[9] or None,sample_bytes=w[10],numeric_bits=w[11],bandwidth_index=(w[40]>>4)&7,
            submitted=w[16],completed=w[17],usb_failures=w[18],rejected=w[19],callback_errors=w[20],
            stop_drops=w[21],bytes=w[22]+(w[23]<<32),worker_active_us=None,
            cp_held=bool(w[15]),cp_phase=w[32],cp_error=w[33],cp_published=w[34],cp_released=w[35],
            cp_flags=w[36],dma_idle=bool(w[37]),iq_mapping_verified=bool(w[40]&1),band=w[40]>>8,gain_index=w[45],frequency_hz=w[47])
        if with_recovery:
            data=client.request(48)
            if len(data)!=96: raise ValueError('BW0 recovery status size differs')
            r=struct.unpack('<24I',data)
            if r[:2]!=(0x31524353,1) or r[2]!=w[5]:
                raise ValueError('BW0 recovery ABI/session differs')
            result['recovery']=dict(epoch=r[2],prepared_epochs=r[3],full_ring_stops=r[4],
                attempts=r[5],completed=r[6],pending=bool(r[7]),observed_gap_total_ms=r[8]+(r[9]<<32),
                observed_last_gap_ms=r[10],observed_max_gap_ms=r[11],ongoing_observed_gap_ms=r[12],
                session_elapsed_ms=r[13],duration_ms=r[14],stop_requested=bool(r[15]),
                gap_is_software_observation=bool(r[16]),lost_samples_known=bool(r[17]),
                clock_started=bool(r[18]),capture_epoch=r[19],cancelled=r[20])
        return result
    data=client.request(40)
    if len(data)!=128:
        raise ValueError('raw USB status size differs')
    words=struct.unpack('<32I',data)
    if words[:2]!=(0x31525153,1):
        raise ValueError('raw USB status ABI differs')
    names=['magic','abi','install_status','interface','pipe','enabled','state','error','epoch',
        'duration_ms','elapsed_ms','block_bytes','slots','submitted','completed','usb_failures',
        'rejected','callback_errors','bytes_low','bytes_high','active_us_low','active_us_high','wakeups','source']
    result=dict(zip(names,words))
    result['bytes']=words[18]+(words[19]<<32)
    result['worker_active_us']=words[20]+(words[21]<<32)
    return result


def classify(report):
    """Account for transport bytes separately from the decision to continue.

    No payload inspection and no strict zero-loss gate. Device completion is
    not proof that the application consumed every completed USB byte.
    """
    device,host=report['after'],report['host']
    difference=device['bytes']-host['bytes']
    report['byte_accounting']=dict(device_completed_bytes=device['bytes'],
        host_consumed_bytes=host['bytes'],device_minus_host_bytes=difference,
        state='balanced' if not difference else 'host_shortfall' if difference>0 else 'host_excess',
        lost_sample_positions_known=False,
        shortfall_cause='unknown: may include shutdown discards or receive loss' if difference>0 else None)
    source=2 if report.get('source')=='bw0_capture' else 1
    recovery=device.get('recovery')
    interrupted=bool(recovery and (recovery['full_ring_stops'] or recovery['attempts']))
    duration_reached=(source==1 or (device['elapsed_ms']>=report['config']['duration_ms'] and
        (recovery is not None or not device.get('cp_flags',0)&2)))
    report['requested_duration_reached']=duration_reached
    transport_completed=(device['epoch']==report['epoch'] and device['source']==source and duration_reached and
        device['state']==3 and not device['error'] and
        not any(device[name] for name in ('usb_failures','rejected','callback_errors')) and
        report['host_exit_code']==0 and not host.get('win32_error',0) and
        not host.get('file_error',0) and host['bytes']>0)
    report['transport_completed']=transport_completed
    report['status']=('failed' if not transport_completed or difference<0 else
                      'completed_with_gaps' if interrupted else 'completed_with_loss' if difference else 'passed')
    report['source_interrupted']=interrupted
    report['host_file_dropped_bytes']=host.get('file_dropped_bytes',0)
    if transport_completed and difference>=0 and report['host_file_dropped_bytes'] and not interrupted:
        report['status']='completed_with_loss'
    report['sustained_source_supply_verified']=(source==2 and transport_completed and not interrupted and
        report.get('steady_device_bytes_per_second',0)>=7680000)
    if recovery is not None:
        report['source_recovery']=recovery
        report['recovery_gap_scope']='AP observation of prior source STOP to next epoch metadata ready; not exact RF/sample timing'
    report['zero_loss_required']=False
    report['proves_rf_capture']=False
    report['host_steady_throughput_measured']=False
    report['bw0_steady_device_rate_met']=(report.get('steady_device_bytes_per_second',0)>=7680000)
    report['bw0_capture_ready']=False  # fixed-buffer completion does not validate the producer


def cleanup(client,process,start_attempted,stop_operation=42):
    """A missing START reply may still mean accepted; STOP failure must not
    prevent host cleanup. Report cleanup errors without replacing the cause.
    """
    errors=[]
    if start_attempted:
        try:
            client.request(stop_operation)
        except Exception as error:
            errors.append('device stop: '+str(error))
    if process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception as error:
            errors.append('host terminate: '+str(error))
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception as kill_error:
                errors.append('host kill: '+str(kill_error))
    return errors


def validate_output_paths(report_path, raw_path):
    if report_path.exists():
        raise ValueError('choose a new report path')
    if raw_path is not None:
        if raw_path.resolve()==report_path.resolve():
            raise ValueError('raw data and JSON report must use different paths')
        if raw_path.exists():
            raise ValueError('choose a new raw data path')
        if not raw_path.parent.is_dir():
            raise ValueError('raw data parent directory must already exist')


def record_raw_file(report, path):
    """Metadata only, after receiver exit; never read/hash the IQ payload."""
    size=path.stat().st_size if path.is_file() else None
    host_bytes=report.get('host',{}).get('bytes')
    host=report.get('host',{})
    written=host.get('file_written_bytes',host_bytes)
    dropped=host.get('file_dropped_bytes',0)
    bw0=report.get('source')=='bw0_capture'
    report['raw_file']=dict(path=str(path.resolve()),bytes=size,
        host_consumed_bytes=host_bytes,
        length_matches_host=size is not None and host_bytes is not None and size==host_bytes,
        reported_written_bytes=written,host_queue_dropped_bytes=dropped,
        length_matches_writer=size is not None and written is not None and size==written,
        accounted_host_bytes=written+dropped if written is not None else None,
        source='bw0_capture' if bw0 else 'fixed_test_pattern',
        sample_bytes=4 if bw0 else None,
        storage='two little-endian 16-bit lanes, signed 12-bit fields at bits 15:4' if bw0 else None,
        iq_lane_mapping_verified=report.get('after',{}).get('iq_mapping_verified',False) if bw0 else False,
        trailing_bytes=size%4 if bw0 and size is not None else None,
        payload_inspected=False)
    if (not report['raw_file']['length_matches_writer'] or written is None or host_bytes is None or
        written+dropped!=host_bytes or host.get('file_error',0) or host.get('file_pending_blocks',0) or
        host.get('file_writer_alive',False)):
        report['status']='failed'
    elif dropped and report['status']=='passed':
        report['status']='completed_with_loss'


def run(args):
    bw0=args.source=='bw0'
    selector=getattr(args,'experimental_pre_selector',None)
    report=dict(recorded_at=datetime.now().astimezone().isoformat(),source='bw0_capture' if bw0 else 'fixed_ap_buffer_benchmark',
        rf_capture=bw0,proves_external_rf_reception=False,application_crc=False,data_headers=False,application_retries=False,
        config=dict(duration_ms=args.milliseconds,block_bytes=args.block_bytes,slots=args.slots,
                    requests=args.requests,request_bytes=args.request_bytes,raw_io=args.raw_io,
                    file_mode=('synchronous' if args.sync_file else 'queued') if args.iq_output else 'none',
                    file_queue_blocks=args.file_queue_blocks if args.iq_output and not args.sync_file else 0))
    with StopEvent() as stop_event, ControlClient(args.port,timeout_ms=3000) as client:
        info=client.info()
        validate_source_capabilities(info,args.source)
        experimental_bw=validate_experimental_profile(info,selector)
        if not bw0:
            ownership=check_fixed_source_ownership(client,info)
            if ownership is not None: report['bw0_ownership_before_fixed_test']=ownership
        before=status(client,args.source)
        recovery_enabled=bw0 and info.get('bw0_recovery_status_operation')==48
        report['monitor']=info
        report['control_backend']='native_windows_sdr_usb_dll'
        report['before']=before
        if before['install_status'] or not before['enabled'] or before['state'] in (1,2):
            raise ValueError('raw USB endpoint is not ready/idle: '+json.dumps(before))
        if bw0:
            if info.get('bw0_config_operation')!=47:
                raise ValueError('BW0 firmware has no pre-capture configuration interface')
            if args.band!=5 and args.band not in info.get('bw0_rf_profiles',[]):
                raise ValueError('requested RF profile is not advertised by this firmware')
            if selector is not None:
                client.request(47,struct.pack('<5I',2,args.band,args.frequency_hz,args.gain_index,experimental_bw))
            else:client.request(47,struct.pack('<4I',1,args.band,args.frequency_hz,args.gain_index))
            configured=status(client,args.source)
            if configured['frequency_hz']!=args.frequency_hz or configured['gain_index']!=args.gain_index:
                raise ValueError('BW0 configured parameter readback differs')
            if configured['band'] not in (args.band,0) or (args.band!=5 and configured['band']!=args.band):
                raise ValueError('BW0 configured RF profile readback differs')
            report['configured']=configured
            if selector is not None:
                if configured['sample_rate_nominal_hz'] is not None or configured['bandwidth_index']!=experimental_bw:
                    raise ValueError('experimental unknown-rate/mode readback differs; no START sent')
                report['experimental_profile']=dict(rf_mode=5,cp_pre_selector=selector,sample_rate_hz=None,
                    sample_rate_known=False,frequency_axis_calibrated=False)
            report['config'].update(band=args.band,frequency_hz=args.frequency_hz,gain_index=args.gain_index)
        command=[str(args.receiver),'--milliseconds',str(args.milliseconds+(20000 if bw0 else 2500)),
                 '--requests',str(args.requests),'--request-bytes',str(args.request_bytes),
                 '--stop-event',stop_event.name]
        if args.raw_io:
            command+=['--raw-io']
        if args.iq_output:
            command+=['--output',str(args.iq_output)]
            command+=['--file-queue-blocks',str(args.file_queue_blocks)]
            if args.sync_file: command+=['--sync-file']
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        lines=queue.Queue()
        def stderr_reader():
            for line in process.stderr:
                lines.put(line.rstrip())
        thread=threading.Thread(target=stderr_reader,daemon=True)
        thread.start()
        start_attempted=False
        stderr=[]
        try:
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                try:
                    line=lines.get(timeout=0.1)
                except queue.Empty:
                    if process.poll() is not None:
                        raise RuntimeError('native receiver exited before ready')
                    continue
                stderr.append(line)
                if line=='ready':
                    break
            else:
                raise TimeoutError('native receiver did not become ready')
            start_attempted=True
            response=client.request(45 if bw0 else 41,struct.pack('<4I',1,args.milliseconds,0 if bw0 else args.block_bytes,0 if bw0 else args.slots))
            if len(response)!=4:
                raise ValueError('start epoch response differs')
            report['epoch']=struct.unpack('<I',response)[0]
            samples=[]
            report['device_samples']=samples
            deadline=time.monotonic()+args.milliseconds/1000+(20 if bw0 else 5)
            while time.monotonic()<deadline:
                current=status(client,args.source,recovery_enabled)
                samples.append(dict(host_time=time.monotonic(),**current))
                if current['epoch']==report['epoch'] and current['state'] in (3,4):
                    break
                if process.poll() is not None:
                    raise RuntimeError('host receiver exited before source drained')
                time.sleep(0.2)
            else:
                raise TimeoutError('device benchmark did not reach terminal state')
            report['device_samples']=samples
            report['after']=current
            stop_event.signal()
            report['host_stop_signalled_after_device_terminal']=True
            process.wait(timeout=5)
            output=process.stdout.read()
            report['host']=json.loads(output)
            report['host_exit_code']=process.returncode
            thread.join(timeout=1)
            while not lines.empty():
                stderr.append(lines.get_nowait())
            report['host_stderr']=stderr
            if len(samples)>=3:
                middle=samples[1:-1]
                if len(middle)>=2:
                    first,last=middle[0],middle[-1]
                    interval=last['elapsed_ms']-first['elapsed_ms']
                    if interval>0:
                        report['steady_device_bytes_per_second']=(last['bytes']-first['bytes'])*1000/interval
            report['device_bytes_per_second']=current['bytes']*1000/max(current['elapsed_ms'],1)
            report['worker_active_fraction']=(current['worker_active_us']/max(current['elapsed_ms']*1000,1)
                if current['worker_active_us'] is not None else None)
            report['worker_active_is_total_cpu_utilization']=False
            classify(report)
            if selector is not None:
                report['sustained_source_supply_verified']=False
                report['bw0_steady_device_rate_met']=False
        except Exception as error:
            report['status']='failed'
            report['error']=str(error)
        finally:
            report['start_attempted']=start_attempted
            report['cleanup_errors']=cleanup(client,process,start_attempted,46 if bw0 else 42)
            if report['cleanup_errors']:
                report['status']='failed'
            report['host_stderr']=stderr
            if args.iq_output:
                record_raw_file(report,args.iq_output)
        return report


def validate_rf_config(band,frequency_hz,gain_index):
    envelope={1:(2110000000,2169900000),3:(1805000000,1879900000),5:(869000000,893900000),7:(2620000000,2689900000),8:(925000000,959900000),
              18:(860000000,874900000),19:(875000000,889900000),26:(859000000,893900000),
              38:(2570000000,2619900000),39:(1880000000,1919900000),40:(1884375000,2790625000),41:(2496000000,2689900000)}.get(band)
    if envelope is None or not envelope[0]<=frequency_hz<=envelope[1] or frequency_hz%100 or not 0<=gain_index<=124:
        raise ValueError('BW0 software envelopes support B1/B3/B5/B7/B8/B18/B19/B26/B38/B39/B40/B41; use a center inside its configured range, 100-Hz units, gain index 0..124. No physical passband guarantee.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',required=True)
    parser.add_argument('--source',choices=('fixed','bw0'),default='fixed')
    parser.add_argument('--band',type=int,default=5)
    parser.add_argument('--frequency-hz',type=int)
    parser.add_argument('--gain-index',type=int)
    parser.add_argument('--experimental-pre-selector',type=int,choices=(5,6,7))
    parser.add_argument('--receiver',type=Path,default=ROOT/'outputs/host/windows/sdr_receive.exe')
    parser.add_argument('--milliseconds',type=int,default=10000)
    parser.add_argument('--block-bytes',type=int,default=16384)
    parser.add_argument('--slots',type=int,default=8)
    parser.add_argument('--requests',type=int,default=8)
    parser.add_argument('--request-bytes',type=int,default=65536)
    parser.add_argument('--raw-io',action='store_true')
    parser.add_argument('--iq-output',type=Path)
    parser.add_argument('--sync-file',action='store_true',help='use synchronous file callback for comparison')
    parser.add_argument('--file-queue-blocks',type=int,default=32)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.experimental_pre_selector is not None and (args.source!='bw0' or not 100<=args.milliseconds<=2000):
        parser.error('PRE experiments require --source bw0 and finite100..2000ms')
    if not 2<=args.file_queue_blocks<=256 or args.file_queue_blocks*args.request_bytes>256*1024*1024:
        parser.error('file queue requires 2..256 blocks and at most 256 MiB')
    if args.source=='fixed' and (args.frequency_hz is not None or args.gain_index is not None):
        parser.error('RF parameters require --source bw0')
    if args.source=='bw0':
        if args.frequency_hz is None: args.frequency_hz={1:2140000000,3:1842500000,5:881500000,7:2655000000,8:942500000,
            18:867500000,19:882500000,26:876500000,
            38:2595000000,39:1900000000,40:2330000000,41:2595000000}.get(args.band,0)
        if args.gain_index is None: args.gain_index=40
        try:
            validate_rf_config(args.band,args.frequency_hz,args.gain_index)
        except ValueError as error:
            parser.error(str(error))
    if args.source=='bw0': args.block_bytes,args.slots=8000,7
    if not 100<=args.milliseconds<=60000 or (args.source=='fixed' and (not 1<=args.slots<=64 or not 512<=args.block_bytes<=65024 or args.block_bytes%512 or args.slots*args.block_bytes>262144)):
        parser.error('device benchmark configuration outside supported bounds')
    try:
        validate_output_paths(args.output,args.iq_output)
    except ValueError as error:
        parser.error(str(error))
    try:
        result=run(args)
    except Exception as error:
        result=dict(status='failed',error=str(error),rf_capture=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    return int(result['status'] not in ('passed','completed_with_loss','completed_with_gaps'))


if __name__=='__main__':
    raise SystemExit(main())
