"""Live raw IQ pipe with incremental framed QPSK/OFDM demodulation.

The receiver emits binary IQ on stdout; status JSON is on stderr. The transport
path is bounded and continuously drained through device STOP. Finite B210
playback and synthetic self-tests share the versioned waveform protocols.
"""
import argparse, json, subprocess, sys, threading, time, os, queue, signal, hashlib
from collections import deque
from pathlib import Path
import numpy as np
from comm_protocol import stream,demod,QPSKReceiver
from comm_ofdm_realtime import OFDMReceiver, VERSION as OFDM_VERSION

def delivered_receiver():
    """Use the same Windows release selected by the host manifest."""
    directory=Path(__file__).resolve().parents[1]/'outputs/host'
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    return directory/manifest['components']['windows']/'sdr_receive.exe'

class FrameTracker:
    """Sequence-span accounting; host gaps deliberately split the denominator."""
    def __init__(self, sample_rate=1920000, source_metadata=None):
        self.fs=sample_rate;self.frames=0;self.unique=0;self.missing=0
        self.duplicates=0;self.reordered=0;self.segments=0
        self.first=None;self.last=None;self.last_sample=None
        self.first_host_time=None;self.last_host_time=None
        self.first_sample=None;self.pending_gap=None
        self.recoveries=deque(maxlen=1000);self.frame_gaps=deque(maxlen=1000);self.recovery_count=0
        self.source=None
        if source_metadata and source_metadata.get('sequence_repeats') is False:
            count=source_metadata.get('complete_frames')
            first=source_metadata.get('first_sequence')
            samples=source_metadata.get('samples',0)
            frame_samples=source_metadata.get('frame_samples',0)
            if (isinstance(count,int) and 0<count<2**32 and
                    isinstance(first,int) and 0<=first<2**32 and
                    isinstance(frame_samples,int) and frame_samples>0 and
                    count<=samples//frame_samples):
                self.source=dict(count=count,first=first,seen=bytearray((count+7)//8),
                    good=bytearray((count+7)//8),unique=0,error_free=0,
                    minimum=None,maximum=None,outside=0)
    def gap(self, now):
        self.last=None;self.last_sample=None
        if self.pending_gap is None:self.pending_gap=now
    def feed(self, events, now):
        for event in events:
            seq=event['sequence'];sample=event.get('rx_sample_index')
            if self.source is not None:
                source=self.source;index=(seq-source['first'])&0xffffffff
                if index<source['count']:
                    byte,bit=divmod(index,8);flag=1<<bit
                    if not source['seen'][byte]&flag:
                        source['seen'][byte]|=flag;source['unique']+=1
                    if event.get('bit_errors')==0 and not source['good'][byte]&flag:
                        source['good'][byte]|=flag;source['error_free']+=1
                    source['minimum']=index if source['minimum'] is None else min(source['minimum'],index)
                    source['maximum']=index if source['maximum'] is None else max(source['maximum'],index)
                else:source['outside']+=1
            self.frames+=1
            if self.first is None:self.first=seq;self.first_sample=sample;self.first_host_time=now
            delta=(seq-self.last)&0xffffffff if self.last is not None else None
            if delta==0:self.duplicates+=1
            else:
                self.unique+=1
                if delta is None:self.segments+=1
                elif 1<delta<100000:
                    self.missing+=delta-1
                    if sample is not None and self.last_sample is not None:
                        self.frame_gaps.append((sample-self.last_sample)*1000/self.fs)
                elif delta>=100000:self.reordered+=1;self.segments+=1
            if self.pending_gap is not None:
                self.recoveries.append(max(0.,now-self.pending_gap)*1000)
                self.recovery_count+=1
                self.pending_gap=None
            self.last=seq;self.last_sample=sample;self.last_host_time=now
    def source_file_accounting(self):
        scope=('Acquisition relative to complete frames in the finite source file, including '
               'leading/trailing and host gaps. Not measured physical transmitted-frame count, '
               'RF start/end timing or precise sample loss.')
        if self.source is None:
            return dict(available=False,scope=scope,
                reason='Requires finite source metadata with unique sequences and complete frame count.')
        source=self.source;n=source['count'];first,last=source['minimum'],source['maximum']
        return dict(available=True,complete_source_frames=n,
            validated_unique_source_frames=source['unique'],
            error_free_unique_source_frames=source['error_free'],
            source_file_frame_yield=source['unique']/n,
            error_free_source_file_frame_yield=source['error_free']/n,
            unvalidated_source_frames=n-source['unique'],
            leading_unvalidated_frames=first,
            trailing_unvalidated_frames=n-1-last if last is not None else None,
            internal_unvalidated_frames=last-first+1-source['unique'] if first is not None else None,
            out_of_source_range_headers=source['outside'],scope=scope)
    def summary(self):
        expected=self.unique+self.missing
        return dict(validated_frames=self.frames,first_sequence=self.first,last_sequence=self.last,
            first_rx_sample_index=self.first_sample,last_rx_sample_index=self.last_sample,
            unique_validated_frames=self.unique,missing_within_validated_spans=self.missing,
            validated_span_expected_frames=expected,
            validated_span_success_ratio=self.unique/expected if expected else None,
            segments=self.segments,duplicates=self.duplicates,reordered=self.reordered,
            host_gap_recoveries=self.recovery_count,
            host_gap_recovery_p95_ms=float(np.percentile(self.recoveries,95)) if self.recoveries else None,
            host_gap_recovery_max_ms=max(self.recoveries) if self.recoveries else None,
            recovery_pending=self.pending_gap is not None,
            missed_frame_inter_valid_gap_max_ms=max(self.frame_gaps) if self.frame_gaps else None,
            scope='Validated sequence spans only, split at host gaps/reordered sequences; excludes unknown leading/trailing frames and does not prove full-TX synchronization. Recovery is host-observed gap detection to next validated frame, not RF propagation latency.')

class IQAmplitude:
    """Stratified host-side clipping statistics without requiring raw files."""
    def __init__(self):
        self.blocks=0;self.samples=0;self.rails=0;self.peak=0.;self.power=0.;self.max_fraction=0.
    def feed(self, z):
        self.blocks+=1
        if self.blocks % 16 != 1 or not len(z):return
        ar,aq=np.abs(z.real),np.abs(z.imag)
        rails=int(np.count_nonzero(ar>=2040/2048)+np.count_nonzero(aq>=2040/2048))
        self.samples+=len(z);self.rails+=rails
        self.peak=max(self.peak,float(ar.max()),float(aq.max()))
        self.max_fraction=max(self.max_fraction,rails/(2*len(z)))
        self.power+=float(np.sum(ar*ar+aq*aq,dtype=np.float64))
    def summary(self):
        return dict(sampled_complex_samples=self.samples,
            max_abs_lane_native12=int(round(self.peak*2048)),
            near_rail_lane_fraction=self.rails/(2*self.samples) if self.samples else None,
            max_sampled_block_near_rail_fraction=self.max_fraction,
            lane_rms_native12=2048*(self.power/(2*self.samples))**.5 if self.samples else None,
            scope='Every16th decoded host block, including startup/TX-off; near rail >=2040/2048. No digital clipping does not rule out analog compression.')

class IQRing:
    def __init__(self, capacity): self.q=deque();self.capacity=capacity;self.dropped=0;self.bytes=0
    def push(self,b):
        n=len(b)//4*4
        if n<len(b): b=b[:n]
        self.q.append(b);self.bytes+=len(b)
        while self.bytes>self.capacity and self.q:
            x=self.q.popleft();self.bytes-=len(x);self.dropped+=len(x)//4
    def pop(self,n):
        out=bytearray()
        while self.q and len(out)<n:
            x=self.q.popleft();take=min(n-len(out),len(x));out+=x[:take];self.bytes-=take
            if take<len(x):self.q.appendleft(x[take:])
        return bytes(out)

class IQPipe:
    """Drain native stdout even when decoding/waiting is slow.

    Bounded drop-oldest storage never blocks STOP/drain. On overrun, discard
    a batch to leave recovery room instead of resetting the demodulator for
    every subsequent read. Positions stay in host statistics, never payload.
    """
    def __init__(self, pipe, capacity=16*1024*1024):
        self.pipe=pipe;self.capacity=capacity;self.q=deque()
        self.condition=threading.Condition();self.bytes=0;self.total=0
        self.dropped=0;self.high_water=0;self.eof=False;self.error=None
        self.overrun_events=0;self.max_overrun_drop=0
        self.read_count=0;self.min_read_bytes=None;self.max_read_bytes=0
        self.thread=threading.Thread(target=self._read,daemon=True)
        self.thread.start()
    def _append(self,b):
        # Caller holds condition. Preserve absolute byte positions even when
        # a slow consumer loses data; sample bytes themselves are untouched.
        at=self.total;self.total+=len(b)
        self.read_count+=1
        self.min_read_bytes=min(self.min_read_bytes or len(b),len(b))
        self.max_read_bytes=max(self.max_read_bytes,len(b))
        self.q.append((at,time.monotonic(),b));self.bytes+=len(b)
        if self.bytes>self.capacity:
            self.overrun_events+=1
            dropped=0
            while self.bytes>self.capacity//2 and self.q:
                _,_,old=self.q.popleft();self.bytes-=len(old);dropped+=len(old)
            self.dropped+=dropped
            self.max_overrun_drop=max(self.max_overrun_drop,dropped)
        self.high_water=max(self.high_water,self.bytes);self.condition.notify()
    def _read(self):
        tail=b''
        try:
            while True:
                b=self.pipe.read(65536)
                if not b:break
                b=tail+b;n=len(b)//4*4;tail=b[n:];b=b[:n]
                if not b:continue
                with self.condition:
                    self._append(b)
            if tail:self.error='incomplete trailing complex sample (%d bytes)'%len(tail)
        except (OSError,ValueError) as exc:
            self.error=str(exc)
        finally:
            with self.condition:self.eof=True;self.condition.notify_all()
    def pop(self, timeout=.1):
        with self.condition:
            if not self.q and not self.eof:self.condition.wait(timeout)
            if not self.q:return None
            row=self.q.popleft();self.bytes-=len(row[2]);return row

def receiver_metadata(text):
    for line in reversed(text.splitlines()):
        try:
            value=json.loads(line)
            if isinstance(value,dict) and 'device_drained' in value:return value
        except ValueError:pass
    return None

def quality_metrics_passed(modulation, summary):
    """Payload quality only; never infer acquisition/lifecycle from good BER."""
    if not summary.get('frames'):return False
    limits={'decoded_frame_error_rate':.01 if modulation=='qpsk' else .05,
            'evm_median_rms':.125 if modulation=='qpsk' else .15}
    if modulation=='qpsk':limits['ber']=1e-3
    return all(summary.get(k) is not None and 0<=summary[k]<limit for k,limit in limits.items())

def tx_ready_line(line, repeat=False):
    # UHD's finite-file Done! is an end marker, not a TX-ready marker.
    return ('Press Ctrl + C' in line) if repeat else ('Checking TX: LO: locked' in line)

def _kill_tree(proc, grace_s=3.0, orphan_serial=None):
    """Best-effort Windows process-tree cleanup; return an auditable result."""
    if proc is None:
        return {'pid': None, 'initially_running': False, 'terminated': False,
                'killed': False, 'taskkill': False, 'still_running': False}
    result = {'pid': proc.pid, 'initially_running': proc.poll() is None,
              'terminated': False, 'killed': False, 'taskkill': False,
              'still_running': False}
    if proc.poll() is None:
        # Prefer the Windows tree operation for UHD: the executable may have
        # helper children which outlive the parent after a normal terminate.
        if os.name == 'nt':
            try:
                tk = subprocess.run(
                    ['taskkill', '/T', '/F', '/PID', str(proc.pid)],
                    capture_output=True, text=True, timeout=10)
                result['taskkill'] = tk.returncode == 0
                result['taskkill_output'] = (tk.stdout + tk.stderr)[-1000:]
            except (OSError, subprocess.TimeoutExpired) as exc:
                result['taskkill_error'] = str(exc)
        try:
            proc.terminate(); result['terminated'] = True
        except OSError:
            pass
        try:
            proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            try:
                proc.kill(); result['killed'] = True
            except OSError:
                pass
            try:
                proc.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                # Retry the tree operation after a stubborn direct child.
                if os.name == 'nt' and not result['taskkill']:
                    try:
                        tk = subprocess.run(
                            ['taskkill', '/T', '/F', '/PID', str(proc.pid)],
                            capture_output=True, text=True, timeout=10)
                        result['taskkill'] = tk.returncode == 0
                        result['taskkill_output'] = (tk.stdout + tk.stderr)[-1000:]
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        result['taskkill_error'] = str(exc)
                try:
                    proc.wait(timeout=grace_s)
                except subprocess.TimeoutExpired:
                    pass
    result['still_running'] = proc.poll() is None
    # UHD's Windows example can detach a same-image helper after the parent
    # exits.  The Popen handle then looks finished although the B210 remains
    # claimed.  Enumerate only this experiment's serial-tagged TX processes.
    result['orphan_pids'] = []
    if orphan_serial and os.name == 'nt':
        try:
            import psutil
            for child in psutil.process_iter(['pid','name','cmdline']):
                info=child.info
                if info['pid']==getattr(proc,'pid',None): continue
                if (str(info.get('name','')).lower()=='tx_samples_from_file.exe' and
                        orphan_serial in ' '.join(info.get('cmdline') or [])):
                    if not _pid_running(info['pid']):
                        continue
                    try:
                        child.kill(); child.wait(timeout=grace_s)
                        result['orphan_pids'].append({'pid':info['pid'],'released':True})
                    except Exception as exc:
                        result['orphan_pids'].append({'pid':info['pid'],'released':False,'error':str(exc)})
        except Exception as exc:
            result['orphan_scan_error']=str(exc)
    result['still_running'] = result['still_running'] or bool(
        [x for x in result.get('orphan_pids',[]) if not x.get('released',False)])
    return result

def _drain_stderr(pipe):
    if pipe is None:
        return ''
    try:
        return pipe.read().decode(errors='replace')[-4000:]
    except (OSError, ValueError):
        return ''

def _pid_running(pid):
    if os.name != 'nt':
        return True
    try:
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.windll.kernel32
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        h=kernel.OpenProcess(0x1000, False, int(pid))
        if not h:
            return False
        code=wintypes.DWORD()
        ok=kernel.GetExitCodeProcess(h, ctypes.byref(code))
        kernel.CloseHandle(h)
        return bool(ok and code.value==259)
    except Exception:
        return True

def _live_uhd_pids(serial):
    if os.name != 'nt':
        return []
    try:
        import psutil
        out=[]
        for p in psutil.process_iter(['pid','name','cmdline']):
            info=p.info
            if (str(info.get('name','')).lower()=='tx_samples_from_file.exe' and
                    serial in ' '.join(info.get('cmdline') or []) and
                    _pid_running(info['pid'])):
                out.append(info['pid'])
        return out
    except Exception:
        return []

def _make_stop_event(name):
    if os.name != 'nt': return None
    import ctypes
    from ctypes import wintypes
    create=ctypes.windll.kernel32.CreateEventW
    create.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.BOOL,wintypes.LPCWSTR]
    create.restype=wintypes.HANDLE
    h=create(None, True, False, name)
    return h or None

def _signal_stop_event(h):
    if h and os.name == 'nt':
        import ctypes
        ctypes.windll.kernel32.SetEvent(ctypes.c_void_p(h))

def _close_stop_event(h):
    if h and os.name == 'nt':
        import ctypes
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(h))

def _graceful_tx_stop(proc):
    if not proc or proc.poll() is not None or os.name != 'nt':
        return False
    try:
        proc.send_signal(signal.CTRL_BREAK_EVENT)
        proc.wait(timeout=10)
        return True
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False

def qpsk_decimate(raw,sps=8):
    if len(raw)<4*sps:return 0,0
    w=np.frombuffer(raw[:len(raw)//4*4],dtype='<u4')
    i=((w&0xffff).astype('<u2').view('<i2').astype(np.float32))/32768
    q=((w>>16).astype('<u2').view('<i2').astype(np.float32))/32768
    z=i-1j*q; z=z[:len(z)//sps*sps].reshape(-1,sps).mean(1)
    if len(z)<2:return 0,0
    d=z[1:]*np.conj(z[:-1]); valid=np.abs(d)>1e-5
    sym=np.angle(d[valid]); decisions=np.sign(np.cos(sym))+1j*np.sign(np.sin(sym))
    return int(len(decisions)),float(np.mean(np.abs(np.abs(decisions)-np.sqrt(2))))

def decode_iq(raw):
    words=np.frombuffer(raw[:len(raw)//4*4],dtype='<u4')
    i=((words&0xffff).astype('<u2').view('<i2').astype(np.int32)>>4).astype(np.float32)/2048.0
    q=((words>>16).astype('<u2').view('<i2').astype(np.int32)>>4).astype(np.float32)/2048.0
    return i-1j*q

def synthetic():
    rng=np.random.default_rng(1);bits=rng.integers(0,2,4096);z=(1-2*bits[0::2])+1j*(1-2*bits[1::2]);return z

def communication_sample_rate(bandwidth_index, tx_rate=None):
    rates = {0: 1920000, 1: 3840000}
    if bandwidth_index not in rates:
        raise ValueError('Online communication currently supports BW0/BW1 only')
    expected = rates[bandwidth_index]
    if tx_rate is not None and tx_rate != expected:
        raise ValueError('TX sample rate must match the selected receive bandwidth')
    return expected

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--receiver',type=str);ap.add_argument('--port');ap.add_argument('--frequency-hz',type=int);ap.add_argument('--gain-index',type=int,default=30);ap.add_argument('--bandwidth-index',type=int,default=0);ap.add_argument('--duration-s',type=int,default=10);ap.add_argument('--output',required=True);ap.add_argument('--iq-output');ap.add_argument('--self-test',action='store_true');ap.add_argument('--tx-file');ap.add_argument('--tx-repeat',action='store_true');ap.add_argument('--serial',help='B210 serial required with --tx-file');ap.add_argument('--tx-gain',type=float,default=55);ap.add_argument('--tx-rate',type=int);ap.add_argument('--modulation',choices=('qpsk','ofdm'),default='qpsk');a=ap.parse_args()
    try:
        a.tx_rate=communication_sample_rate(a.bandwidth_index,a.tx_rate)
    except ValueError as exc:
        ap.error(str(exc))
    if a.self_test:
        if a.modulation=='ofdm':
            from comm_ofdm_realtime import stream as ofdm_stream
            z=ofdm_stream(8);receiver=OFDMReceiver(sample_rate=a.tx_rate)
            for at in range(0,len(z),511):receiver.feed(z[at:at+511])
            receiver.feed(np.zeros(64,np.complex64))
            d=receiver.summary();assert d['frames']==8 and d['ber']==0,d
        else:
            z,_=stream(frames=2);receiver=QPSKReceiver(sample_rate=a.tx_rate)
            receiver.feed(z);d=receiver.summary();assert d['frames']==2 and d['ber']<1e-6,d
        json.dump({'status':'passed','mode':a.modulation+'_realtime_frame_selftest','demod':d,'device_accessed':False},open(a.output,'w'),indent=2);print('self-test passed');return 0
    if a.tx_file and not a.serial:ap.error('--tx-file requires --serial from the current UHD query')
    if not a.receiver:a.receiver=str(delivered_receiver())
    if not a.port or not a.frequency_hz: ap.error('real mode requires port and frequency')
    # Capture implementation identity before hardware work. These are program
    # files, never IQ payload hashes, and distinguish future decoder changes.
    project_root=Path(__file__).resolve().parents[1]
    dependency_paths=[Path(__file__).resolve(),Path(__file__).with_name('comm_protocol.py').resolve()]
    if a.modulation=='ofdm':dependency_paths.append(Path(__file__).with_name('comm_ofdm_realtime.py').resolve())
    dependency_paths.extend(p for p in (Path(a.receiver).resolve(),Path(a.receiver).resolve().with_name('sdr_usb.dll')) if p.is_file())
    dependencies={(p.relative_to(project_root).as_posix() if p.is_relative_to(project_root) else p.as_posix()):
        hashlib.sha256(p.read_bytes()).hexdigest() for p in dependency_paths}
    tx=None
    p=None
    cleanup=[]
    rx_error=''
    tx_error=''
    ring=IQRing(16*1024*1024)
    decoder=QPSKReceiver(sample_rate=a.tx_rate) if a.modulation=='qpsk' else OFDMReceiver(sample_rate=a.tx_rate)
    frame_tracker=FrameTracker(a.tx_rate)
    amplitude=IQAmplitude()
    receiver_timed_out=False
    tx_ready=False
    tx_read_thread=None
    tx_log=[]
    normal_capture_stop=False
    receiver_stream_ended=False
    stop_event_handle=None
    stop_event_name=None
    iq_sink=None
    pipe_q=None
    consumed_end=0
    pipe_gaps=0
    queue_ages=deque(maxlen=10000)
    decoded_bytes=0
    drain_discarded_bytes=0
    decode_seconds=0.0
    decode_block_seconds=deque(maxlen=10000)
    def process_row(row, decode=True):
        nonlocal consumed_end,pipe_gaps,decoded_bytes,drain_discarded_bytes,decode_seconds
        at,stamp,b=row
        if decode:
            if at!=consumed_end:
                pipe_gaps+=1
                frame_tracker.gap(time.monotonic())
                if hasattr(decoder,'reset'): decoder.reset()
            queue_ages.append(time.monotonic()-stamp)
            if iq_sink:iq_sink.write(b)
            started=time.perf_counter()
            z=decode_iq(b);amplitude.feed(z)
            events=decoder.feed(z);decoded_bytes+=len(b)
            frame_tracker.feed(events,time.monotonic())
            elapsed=time.perf_counter()-started
            decode_seconds+=elapsed;decode_block_seconds.append(elapsed)
        else:
            drain_discarded_bytes+=len(b)
        consumed_end=at+len(b)
    txcmd=None
    tx_samples=None
    waveform_meta=None
    if a.tx_file:
        if a.modulation in ('ofdm','qpsk'):
            from comm_protocol import VERSION as QPSK_VERSION
            try:
                waveform_meta=json.loads(Path(a.tx_file).with_suffix('.json').read_text())
                expected_protocol=OFDM_VERSION if a.modulation=='ofdm' else QPSK_VERSION
                if (waveform_meta.get('protocol')!=expected_protocol or
                        waveform_meta.get('sample_rate_hz')!=a.tx_rate or
                        (a.modulation=='qpsk' and waveform_meta.get('sequence_repeats') is not False) or
                        os.path.getsize(a.tx_file)!=8*waveform_meta.get('samples',0)):
                    raise ValueError('Waveform protocol/rate/length or unique sequence metadata mismatch')
            except (OSError,ValueError) as exc:
                ap.error(str(exc)+'; regenerate using tools/comm_waveform.py --modulation '+a.modulation)
        tx_samples=os.path.getsize(a.tx_file)//8
        frame_tracker=FrameTracker(a.tx_rate,None if a.tx_repeat else waveform_meta)
        if not a.tx_repeat and tx_samples < int(a.tx_rate*a.duration_s*0.95):
            report={'status':'tx_waveform_too_short','device_accessed':False,'modulation':a.modulation,'frequency_hz':a.frequency_hz,'tx_file':a.tx_file,'tx_samples':tx_samples,'required_samples':int(a.tx_rate*a.duration_s*0.95),'scope':'Finite UHD playback is used to guarantee natural process/USB release; generate a waveform at least the requested duration.'}
            json.dump(report,open(a.output,'w'),indent=2);print(json.dumps(report));return 2
        live_uhd=_live_uhd_pids(a.serial)
        if live_uhd:
            report={'status':'hardware_preflight_failed','device_accessed':False,'modulation':a.modulation,'frequency_hz':a.frequency_hz,'serial':a.serial,'live_uhd_pids':live_uhd,'scope':'A live serial-matched UHD transmitter already exists; no new TX process was started.'}
            json.dump(report,open(a.output,'w'),indent=2);print(json.dumps(report));return 2
        # Limit discovery to the requested B210; probing unrelated UHD
        # backends can fail even while this serial is present and usable.
        probe=subprocess.run(['uhd_find_devices','--args','type=b200,serial='+a.serial],env=dict(os.environ,PATH='C:/Program Files/UHD/bin;'+os.environ.get('PATH','')),capture_output=True,text=True,timeout=15)
        if probe.returncode!=0 or a.serial not in (probe.stdout+probe.stderr):
            report={'status':'hardware_preflight_failed','device_accessed':False,'modulation':a.modulation,'frequency_hz':a.frequency_hz,'serial':a.serial,'uhd_find_devices_exit_code':probe.returncode,'uhd_find_devices_output':(probe.stdout+probe.stderr)[-4000:],'scope':'B210 was not visible before TX launch; no transmitter process was started.'}
            json.dump(report,open(a.output,'w'),indent=2);print(json.dumps(report));return 2
        # uhd_find_devices briefly owns the B210 USB handle while probing.
        # Let UHD release that handle before tx_samples_from_file claims it.
        time.sleep(3.0)
        txcmd=['C:/Program Files/UHD/lib/uhd/examples/tx_samples_from_file.exe','--args','type=b200,serial='+a.serial,'--file',a.tx_file,'--type','float','--rate',str(a.tx_rate),'--freq',str(a.frequency_hz),'--gain',str(a.tx_gain),'--subdev','A:A A:B','--channels','0','--ant','TX/RX']
        if a.tx_repeat: txcmd.append('--repeat')
    # Finite UHD playback can spend tens of seconds loading the B210 FPGA.
    # Keep the receiver alive through that startup; the host-side duration
    # starts only after the TX readiness marker and cleanup still bounds it.
    receiver_ms=(0 if a.duration_s>=60 else min(60000,(a.duration_s+35)*1000)) if a.tx_file else a.duration_s*1000
    if os.name == 'nt':
        stop_event_name='Global\\UIS8910CommStop_%d'%os.getpid()
        stop_event_handle=_make_stop_event(stop_event_name)
        if not stop_event_handle: raise OSError('unable to create receiver STOP event')
    cmd=[a.receiver,'--port',a.port,'--frequency-hz',str(a.frequency_hz),'--gain-index',str(a.gain_index),'--bandwidth-index',str(a.bandwidth_index),'--milliseconds',str(receiver_ms),'--stdout-raw']
    if stop_event_name and stop_event_handle: cmd += ['--stop-event',stop_event_name]
    experiment_error=None
    host_cpu_start=time.process_time()
    timeline_origin=time.monotonic()
    timeline={}
    try:
        if a.iq_output: iq_sink=open(a.iq_output,'xb')
        rx_flags=getattr(subprocess,'CREATE_NO_WINDOW',0) | getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0,creationflags=rx_flags)
        timeline['rx_launched_s']=time.monotonic()-timeline_origin
        # Start the receiver first.  If UIS8910 is still BUSY, it exits here
        # and no UHD transmitter is launched into a doomed session.
        time.sleep(0.5)
        stop=time.monotonic()+a.duration_s+15
        pipe_q=IQPipe(p.stdout)
        if p.poll() is None and txcmd:
            tx_flags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)
            if not a.tx_repeat: tx_flags |= getattr(subprocess,'CREATE_NO_WINDOW',0)
            tx=subprocess.Popen(txcmd,env=dict(os.environ,PATH='C:/Program Files/UHD/bin;'+os.environ.get('PATH','')),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=tx_flags)
            timeline['tx_launched_s']=time.monotonic()-timeline_origin
            txq=queue.Queue(maxsize=256)
            def read_tx():
                try:
                    while True:
                        line=tx.stdout.readline()
                        if not line: break
                        text=line.decode(errors='replace');tx_log.append(text[-1000:]);txq.put(text)
                except (OSError, ValueError): pass
            tx_read_thread=threading.Thread(target=read_tx,daemon=True); tx_read_thread.start()
            ready_deadline=time.monotonic()+(60 if a.duration_s>=60 else 30)
            while time.monotonic()<ready_deadline and tx.poll() is None and not tx_ready:
                try:
                    while True:
                        line=txq.get_nowait()
                        if tx_ready_line(line,a.tx_repeat):
                            tx_ready=True
                            timeline['tx_ready_marker_s']=time.monotonic()-timeline_origin
                except queue.Empty: pass
                row=pipe_q.pop(.1)
                if row is None:
                    if pipe_q.eof: receiver_stream_ended=True;break
                    continue
                process_row(row)
            if not tx_ready:
                tx_log.append('UHD transmitter readiness marker not observed before timeout/exit')
        finite_tx=bool(tx and not a.tx_repeat)
        stop=time.monotonic()+a.duration_s+(5 if finite_tx else 0)
        tx_exit_observed=None
        while time.monotonic()<stop:
            row=pipe_q.pop(1.0)
            if row is None:
                if pipe_q.eof: receiver_stream_ended=True;break
                continue
            process_row(row)
            if finite_tx and tx.poll() is not None:
                if tx_exit_observed is None:
                    tx_exit_observed=time.monotonic()
                    timeline['tx_exit_observed_s']=tx_exit_observed-timeline_origin
                # Keep decoding live input through a small post-exit tail.
                # Do not drain a backlog offline and label it real time.
                if time.monotonic()-tx_exit_observed>=.75:break
        normal_capture_stop=True
        timeline['capture_stop_requested_s']=time.monotonic()-timeline_origin
        _signal_stop_event(stop_event_handle)
        # A finite waveform can exit cleanly; give UHD time to release the
        # B210 instead of killing it immediately after the requested capture.
        if tx and not a.tx_repeat and tx.poll() is None:
            try:
                tx.wait(timeout=max(5.0, os.path.getsize(a.tx_file)/8/a.tx_rate+5.0))
            except subprocess.TimeoutExpired:
                pass
        if tx and tx.poll() is not None:timeline.setdefault('tx_exit_observed_s',time.monotonic()-timeline_origin)
        # Continue draining stdout during native STOP. Tail data is accounted
        # separately, not demodulated later and presented as real-time work.
        drain_deadline=time.monotonic()+15.0
        while time.monotonic()<drain_deadline:
            row=pipe_q.pop(.1)
            if row is None:
                if pipe_q.eof: break
                continue
            process_row(row,decode=False)
            if pipe_q.eof and not pipe_q.q: break
        if p and p.poll() is None:
            try: p.wait(timeout=15)
            except subprocess.TimeoutExpired: receiver_timed_out=True
    except Exception as exc:
        experiment_error=str(exc)
    finally:
        _signal_stop_event(stop_event_handle)
        cleanup.append({'receiver': _kill_tree(p)})
        rx_error=_drain_stderr(p.stderr if p else None)
        graceful_tx=False
        if tx and a.tx_repeat and tx.poll() is None:
            graceful_tx=_graceful_tx_stop(tx)
        tx_cleanup=_kill_tree(tx, orphan_serial=a.serial if tx else None)
        tx_cleanup['graceful_signal']=graceful_tx
        cleanup.append({'tx': tx_cleanup})
        tx_error=_drain_stderr(tx.stderr if tx else None)
        if iq_sink:
            iq_sink.close()
        _close_stop_event(stop_event_handle)
    released=all(not list(x.values())[0]['still_running'] for x in cleanup)
    abnormal_end=receiver_stream_ended and bool(a.tx_file)
    receiver_exit_ok=bool(p is not None and p.returncode==0)
    tx_exit_ok=bool(tx is None or tx.returncode==0)
    meta=receiver_metadata(rx_error)
    report={'status':'completed' if normal_capture_stop and not receiver_timed_out and not abnormal_end and released and receiver_exit_ok and tx_exit_ok else 'receiver_failed','device_accessed':True,'modulation':a.modulation,'frequency_hz':a.frequency_hz,'duration_s':a.duration_s,'iq_output':a.iq_output,'ring_dropped_samples':ring.dropped,'pipe_dropped_bytes':getattr(pipe_q,'dropped',0),'pipe_gap_events':pipe_gaps,'pipe_high_water_bytes':getattr(pipe_q,'high_water',0),'pipe_error':getattr(pipe_q,'error',None),'decoded_bytes':decoded_bytes,'drain_discarded_bytes':drain_discarded_bytes,'queue_age_ms':(1000*float(np.median(queue_ages)) if queue_ages else None),'receiver_exit_code':p.returncode if p else None,'receiver_exit_ok':receiver_exit_ok,'receiver_timed_out':receiver_timed_out,'receiver_stream_ended':receiver_stream_ended,'receiver_stopped_after_capture':normal_capture_stop,'receiver_stderr':rx_error,'tx_exit_code':tx.returncode if tx else None,'tx_exit_ok':tx_exit_ok,'tx_ready':tx_ready,'tx_file':a.tx_file,'tx_repeat':a.tx_repeat,'tx_stderr':tx_error,'tx_log':tx_log[-20:],'cleanup':cleanup,'all_children_released':released,'demodulation':decoder.summary(),'scope':'Live raw IQ transport and online modulation statistics; USB loss location remains unknown.'}
    report.update(receiver_metadata=meta,experiment_error=experiment_error,
        dependencies=dependencies,
        receiver_program=Path(a.receiver).resolve().as_posix(),
        frame_tracking=frame_tracker.summary(),
        source_file_accounting=frame_tracker.source_file_accounting(),
        iq_amplitude=amplitude.summary(),
        host_timeline=dict(timeline,
            first_valid_frame_s=frame_tracker.first_host_time-timeline_origin if frame_tracker.first_host_time is not None else None,
            last_valid_frame_s=frame_tracker.last_host_time-timeline_origin if frame_tracker.last_host_time is not None else None,
            scope='Host-observed times from RX launch sequence; UHD readiness/exit and decode timestamps are not physical RF start/end or propagation latency.'),
        tx_nominal_samples=tx_samples,
        waveform_metadata=waveform_meta,
        configured_sample_rate_hz=a.tx_rate,
        receiver_rate_matches=bool(meta and meta.get('requested_nominal_sample_rate_hz')==a.tx_rate),
        tx_nominal_duration_s=tx_samples/a.tx_rate if tx_samples is not None else None,
        gain_index=a.gain_index,tx_gain_db=a.tx_gain,bandwidth_index=a.bandwidth_index,
        host_process_cpu_seconds=time.process_time()-host_cpu_start,
        decode_seconds=decode_seconds,
        decode_block_p95_ms=(1000*float(np.percentile(decode_block_seconds,95)) if decode_block_seconds else None),
        decode_block_max_ms=(1000*float(max(decode_block_seconds)) if decode_block_seconds else None),
        pipe_read_count=getattr(pipe_q,'read_count',0),
        pipe_min_read_bytes=getattr(pipe_q,'min_read_bytes',None),
        pipe_max_read_bytes=getattr(pipe_q,'max_read_bytes',0),
        pipe_overrun_events=getattr(pipe_q,'overrun_events',0),
        pipe_max_overrun_drop_bytes=getattr(pipe_q,'max_overrun_drop',0),
        pipe_drop_policy='drop_oldest_to_half_capacity_on_overrun',
        queue_age_p95_ms=(1000*float(np.percentile(queue_ages,95)) if queue_ages else None),
        queue_age_max_ms=(1000*float(max(queue_ages)) if queue_ages else None))
    if (experiment_error or not meta or not meta.get('device_drained') or
            any(meta.get(k,0) for k in ('session_error','control_error','cleanup_error','win32_error')) or
            (a.tx_file and (not tx or not tx_ready))):
        report['status']='receiver_failed'
    report['lifecycle_passed']=report['status']=='completed'
    # A clean device/process lifecycle is independent of real-time quality.
    # Never hide a bounded host-queue overrun behind the completed label.
    report['realtime_host_passed']=bool(report['lifecycle_passed'] and
        not report['pipe_dropped_bytes'] and not pipe_gaps and not report['pipe_error'])
    report['quality_metrics_passed']=bool(report['receiver_rate_matches'] and quality_metrics_passed(a.modulation,report['demodulation']))
    tracking=report['frame_tracking']
    report['validated_span_sync_passed']=bool(report['realtime_host_passed'] and
        tracking['validated_span_success_ratio'] is not None and
        tracking['validated_span_success_ratio']>=.99 and
        not tracking['duplicates'] and not tracking['reordered'])
    source_accounting=report['source_file_accounting']
    report['source_file_acquisition_passed']=bool(report['realtime_host_passed'] and
        source_accounting['available'] and source_accounting['source_file_frame_yield']>=.99)
    report['acceptance_scope']='User acceptance is10s real-time wireless transfer/demodulation. Lifecycle, host queue, payload quality, sequence spans and source-file yield are separate; no long-duration stability, full physicalTX-window sync or precise sample-loss claim.'
    json.dump(report,open(a.output,'w'),indent=2);print(json.dumps(report));return 0 if report['status']=='completed' else 1
if __name__=='__main__':raise SystemExit(main())
