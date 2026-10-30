"""Focused host-only checks for raw-pipe shutdown, overload and sample alignment."""
import ctypes
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from comm_realtime import IQPipe, FrameTracker, IQAmplitude, quality_metrics_passed, tx_ready_line, _pid_running, _make_stop_event, _signal_stop_event, _close_stop_event, receiver_metadata


class Fragmented:
    def __init__(self, value): self.value=value;self.index=0
    def read(self, _):
        n=(1,3,17,5,2,31)[self.index%6];self.index+=1
        out=self.value[:n];self.value=self.value[n:];return out


def verify():
    from comm_realtime import communication_sample_rate, delivered_receiver
    manifest=json.loads((Path(__file__).resolve().parents[2]/'outputs/host/manifest.json').read_text(encoding='utf-8'))
    program=delivered_receiver()
    assert program.is_file()
    assert program.parent.name==manifest['components']['windows']
    assert communication_sample_rate(0) == 1920000
    assert communication_sample_rate(1) == 3840000
    for bandwidth, rate in ((1,1920000), (0,3840000), (2,None)):
        try:
            communication_sample_rate(bandwidth,rate)
        except ValueError:
            pass
        else:
            raise AssertionError('Mismatched or unsupported communication rate accepted')
    assert tx_ready_line('Checking TX: LO: locked ...')
    assert not tx_ready_line('Done!') and not tx_ready_line('Checking TX: LO: unlocked')
    assert tx_ready_line('Press Ctrl + C',True)
    assert not quality_metrics_passed('qpsk',dict(frames=0,ber=0,decoded_frame_error_rate=0,evm_median_rms=0))
    assert not quality_metrics_passed('qpsk',dict(frames=10,ber=0,decoded_frame_error_rate=.2,evm_median_rms=.01))
    assert quality_metrics_passed('ofdm',dict(frames=10,ber=.001,decoded_frame_error_rate=.01,evm_median_rms=.03))
    import numpy as np
    amplitude=IQAmplitude();amplitude.feed(np.array([2047/2048-1j, .5+.25j],np.complex64))
    s=amplitude.summary()
    assert s['near_rail_lane_fraction']==.5 and s['max_abs_lane_native12']==2048
    tracker=FrameTracker()
    tracker.feed([dict(sequence=0xfffffffe,rx_sample_index=0),
                  dict(sequence=0,rx_sample_index=2000),
                  dict(sequence=0,rx_sample_index=2000)],1.)
    s=tracker.summary()
    assert s['missing_within_validated_spans']==1 and s['duplicates']==1
    assert s['validated_span_success_ratio']==2/3
    tracker.gap(2.)
    tracker.feed([dict(sequence=100,rx_sample_index=4000)],2.125)
    s=tracker.summary()
    assert s['missing_within_validated_spans']==1 and s['segments']==2
    assert s['host_gap_recovery_max_ms']==125 and not s['recovery_pending']
    # Source-file denominator includes startup/tail and host gaps, counts each
    # source sequence once, and handles uint32 wrap without a growing set.
    plan=dict(sequence_repeats=False,complete_frames=8,first_sequence=0xfffffffc,
              samples=800,frame_samples=100)
    planned=FrameTracker(source_metadata=plan)
    planned.feed([dict(sequence=0xfffffffd,bit_errors=1),
                  dict(sequence=0xfffffffe,bit_errors=0)],1.)
    planned.gap(2.)
    planned.feed([dict(sequence=0,bit_errors=0),dict(sequence=0,bit_errors=0),
                  dict(sequence=2,bit_errors=0),dict(sequence=9,bit_errors=0)],3.)
    source=planned.source_file_accounting()
    assert source['complete_source_frames']==8 and source['validated_unique_source_frames']==4
    assert source['error_free_unique_source_frames']==3 and source['source_file_frame_yield']==.5
    assert source['leading_unvalidated_frames']==1 and source['trailing_unvalidated_frames']==1
    assert source['internal_unvalidated_frames']==2 and source['out_of_source_range_headers']==1
    assert len(planned.source['seen'])==1
    assert not FrameTracker().source_file_accounting()['available']
    assert not FrameTracker(source_metadata=dict(plan,sequence_repeats=True)).source_file_accounting()['available']
    payload=bytes(range(256))*128
    source=IQPipe(Fragmented(payload),capacity=len(payload))
    source.thread.join(3)
    assert source.eof and not source.error and source.dropped==0
    result=bytearray()
    while True:
        row=source.pop(0)
        if row is None:break
        assert row[0]==len(result) and len(row[2])%4==0
        result.extend(row[2])
    assert result==payload, 'fragmented stdout lost or shifted complex samples'

    # No consumer runs while the child writes: native STOP must not be blocked
    # behind a full Python queue. Drops are explicit and the queue stays bounded.
    child=subprocess.Popen([sys.executable,'-c',
        'import sys;sys.stdout.buffer.write(bytes(8*1024*1024));sys.stdout.buffer.flush()'],stdout=subprocess.PIPE)
    source=IQPipe(child.stdout,capacity=8192)
    assert child.wait(timeout=10)==0
    source.thread.join(3)
    assert source.eof and source.total==8*1024*1024
    assert source.dropped+source.bytes==source.total
    assert source.high_water<=8192 and source.dropped>0
    assert source.overrun_events>0 and source.max_overrun_drop>0
    # A stalled reader followed by a continuously slow consumer must get
    # contiguous runs between losses, rather than one reset on every read.
    # Check byte conservation and exact surviving content/positions as well.
    recovery=IQPipe(io.BytesIO(b''),capacity=16*256)
    recovery.thread.join(3)
    delivered=[]
    for group in range(40):
        with recovery.condition:
            for j in range(3):
                offset=recovery.total
                recovery._append(bytes([(offset//256)%256])*256)
        row=recovery.pop(0)
        if row:delivered.append(row)
    while True:
        row=recovery.pop(0)
        if row is None:break
        delivered.append(row)
    assert recovery.total==recovery.dropped+sum(len(row[2]) for row in delivered)
    assert all(row[2]==bytes([(row[0]//256)%256])*256 for row in delivered)
    gaps=sum(b[0]!=a[0]+len(a[2]) for a,b in zip(delivered,delivered[1:]))
    assert 0<gaps<10 and recovery.overrun_events==gaps
    assert recovery.high_water<=recovery.capacity and recovery.bytes==0
    assert receiver_metadata('notice\n{"device_drained":true,"bytes":32}\n')['device_drained']
    assert receiver_metadata('') is None
    # A child that rejects native CLI arguments produces no terminal metadata.
    # The parent must still write a failure report instead of dereferencing None.
    with tempfile.TemporaryDirectory() as temp:
        report_path=Path(temp)/'failed.json'
        failed=subprocess.run([sys.executable,'-B','tools/comm_realtime.py',
            '--receiver',sys.executable,'--port','COM_UNUSED_TEST',
            '--frequency-hz','1900000000','--duration-s','1','--output',str(report_path)],
            capture_output=True,text=True,timeout=15)
        report=json.loads(report_path.read_text())
        assert failed.returncode!=0 and report['status']=='receiver_failed'
        assert report['receiver_metadata'] is None and not report['receiver_rate_matches']
        assert report['all_children_released']
    if os.name=='nt':
        assert _pid_running(os.getpid())
        assert not _pid_running(child.pid)
        handle=_make_stop_event('Local\\UIS8910CommTest_%d'%os.getpid())
        assert handle
        try:
            wait=ctypes.windll.kernel32.WaitForSingleObject
            wait.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
            assert wait(handle,0)==258
            _signal_stop_event(handle)
            assert wait(handle,0)==0
        finally:_close_stop_event(handle)
    return dict(status='passed',device_accessed=False,
        checks=['manifest_selected_default_receiver','native_failure_without_terminal_metadata','bandwidth_rate_agreement','finite_source_frame_denominator_wrap_duplicates_and_gaps','finite_ready_marker_not_done','independent_payload_quality_gate','native12_amplitude_sampling',
                'sequence_span_wrap_missing_duplicate_and_host_gap_recovery',
                'fragmented_sample_alignment','bounded_overload_no_child_deadlock',
                'batched_overrun_contiguous_recovery_and_byte_conservation',
                'explicit_drop_accounting','terminal_metadata','Windows_live_process_and_stop_event'])


if __name__=='__main__':
    report=verify()
    if len(sys.argv)>1:Path(sys.argv[1]).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
