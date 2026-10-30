"""Focused control-lifecycle and byte-accounting tests; no hardware access."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/usb'))
from benchmark import (classify,cleanup,status,StopEvent,validate_output_paths,
                       record_raw_file,validate_rf_config,validate_source_capabilities,check_fixed_source_ownership,
                       validate_experimental_profile)


def main():
    experimental=dict(bw0_experimental_pre_selector=6,bw0_experimental_rf_mode=5,
                      bw0_experimental_rate_known=False,bw0_bandwidth_indices=list(range(6)),bw0_config_abi=2)
    assert validate_experimental_profile(experimental,6)==5
    switch=dict(experimental,bw0_experimental_pre_selectors=[5,6,7]);switch.pop('bw0_experimental_pre_selector')
    assert [validate_experimental_profile(switch,n) for n in (5,6,7)]==[5,6,7]
    assert validate_experimental_profile({},None)==0
    for info,selector in [({},6),(experimental,7),(dict(experimental,bw0_experimental_rf_mode=6),6),
                          (dict(experimental,bw0_experimental_rate_known=True),6),
                          (dict(experimental,bw0_until_stop=True),6),
                          (dict(experimental,bw0_bandwidth_indices=[0,1]),6),
                          (dict(switch,bw0_experimental_pre_selectors=[5,6]),6)]:
        try:validate_experimental_profile(info,selector)
        except ValueError:pass
        else:raise AssertionError('unmatched experiment accepted')
    raw_info=dict(firmware='uis8910-sdr-raw-usb-v1',raw_usb=True,raw_usb_abi=1,
        raw_usb_source='fixed_ap_buffer_benchmark',raw_usb_status_operation=40,
        raw_usb_start_operation=41,raw_usb_stop_operation=42)
    bw0_info=dict(raw_info,firmware='uis8910-sdr-bw0-usb-v1',bw0_usb=True,
        bw0_status_operation=44,bw0_start_operation=45,bw0_stop_operation=46,bw0_config_operation=47)
    for info,source in ((raw_info,'fixed'),(bw0_info,'fixed'),(bw0_info,'bw0')):
        validate_source_capabilities(info,source)
    rejected=[(raw_info,'bw0'),(dict(bw0_info,raw_usb_abi=2),'fixed'),
        (dict(bw0_info,raw_usb_start_operation=45),'fixed'),
        (dict(bw0_info,raw_usb_stop_operation=46),'bw0'),
        (dict(bw0_info,raw_usb_source='unknown'),'fixed'),
        (dict(bw0_info,bw0_config_operation=99),'bw0'),
        (dict(bw0_info,bw0_status_operation=99),'fixed'),
        (dict(bw0_info,bw0_usb=False),'fixed'),
        (dict(bw0_info,firmware='unknown'),'fixed'),(bw0_info,'other')]
    for info,source in rejected:
        try:validate_source_capabilities(info,source)
        except ValueError:pass
        else:raise AssertionError('unknown or mismatched control ABI accepted')
    for hz in (1884375000,2000000000,2330000000,2600000000,2790625000):
        validate_rf_config(40,hz,40)
    for band,hz in ((3,1805000000),(3,1842500100),(3,1879900000),(8,925000000),(8,942500100),(8,959900000)):
        validate_rf_config(band,hz,40)
    for band,lower,upper in ((1,2110000000,2169900000),(38,2570000000,2619900000),
                             (39,1880000000,1919900000),(41,2496000000,2689900000),
                             (7,2620000000,2689900000),(18,860000000,874900000),
                             (19,875000000,889900000),(26,859000000,893900000)):
        for hz in (lower,(lower+upper)//2//100*100,upper): validate_rf_config(band,hz,40)
        for hz in (lower-100,upper+100):
            try:validate_rf_config(band,hz,40)
            except ValueError:pass
            else:raise AssertionError('new profile outside envelope accepted')
    for band,hz in ((40,1884374900),(40,2790625100),(40,881500000),(5,2330000000),
                    (3,1804999900),(3,1879900100),(8,924999900),(8,959900100),(8,1842500000),(34,2017500000)):
        try:
            validate_rf_config(band,hz,40)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid band/center accepted')
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        folder=Path(directory)
        raw=folder/'capture.raw'; metadata=folder/'capture.json'
        validate_output_paths(metadata,raw)
        for report_path,raw_path in ((raw,raw),(metadata,folder/'missing'/'capture.raw')):
            try:
                validate_output_paths(report_path,raw_path)
            except ValueError:
                pass
            else:
                raise AssertionError('unsafe output paths accepted')
        raw.write_bytes(b'\x00'*12)
        saved=dict(status='passed',source='bw0_capture',host={'bytes':12})
        record_raw_file(saved,raw)
        assert saved['status']=='passed' and saved['raw_file']['length_matches_host']
        assert saved['raw_file']['sample_bytes']==4 and not saved['raw_file']['payload_inspected']
        saved['host']['bytes']=16
        record_raw_file(saved,raw)
        assert saved['status']=='failed'
        saved=dict(status='passed',source='bw0_capture',host=dict(bytes=16,file_written_bytes=12,
            file_dropped_bytes=4,file_error=0,file_pending_blocks=0,file_writer_alive=False))
        record_raw_file(saved,raw)
        assert saved['status']=='completed_with_loss' and saved['raw_file']['length_matches_writer']
        assert not saved['raw_file']['length_matches_host'] and saved['raw_file']['host_queue_dropped_bytes']==4
        saved['host']['file_dropped_bytes']=3;record_raw_file(saved,raw)
        assert saved['status']=='failed'
        saved['host'].update(file_dropped_bytes=4,file_writer_alive=True);record_raw_file(saved,raw)
        assert saved['status']=='failed'
        try:
            validate_output_paths(metadata,raw)
        except ValueError:
            pass
        else:
            raise AssertionError('existing raw file accepted')
        missing=dict(status='passed',host={'bytes':12})
        record_raw_file(missing,folder/'absent.raw')
        assert missing['status']=='failed'
    import ctypes
    from ctypes import wintypes
    with StopEvent() as event:
        api=event.api
        api.OpenEventW.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR]
        api.OpenEventW.restype=wintypes.HANDLE
        api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        api.WaitForSingleObject.restype=wintypes.DWORD
        opened=api.OpenEventW(0x100000,False,event.name)  # SYNCHRONIZE, as used by CLI
        assert opened
        try:
            assert api.WaitForSingleObject(opened,0)==258
            event.signal()
            assert api.WaitForSingleObject(opened,0)==0
        finally:
            api.CloseHandle(opened)
    def report(host_bytes=8000):
        return dict(epoch=2,after=dict(epoch=2,source=1,state=3,error=0,bytes=8000,
            usb_failures=0,rejected=0,callback_errors=0),
            host=dict(bytes=host_bytes,win32_error=0,file_error=0),host_exit_code=0)
    exact=report();classify(exact)
    assert exact['status']=='passed' and exact['byte_accounting']['state']=='balanced'
    file_loss=report();file_loss['host']['file_dropped_bytes']=512;classify(file_loss)
    assert file_loss['status']=='completed_with_loss' and file_loss['host_file_dropped_bytes']==512
    assert file_loss['byte_accounting']['state']=='balanced'
    short=report(4000);classify(short)
    assert short['status']=='completed_with_loss' and short['transport_completed']
    assert short['byte_accounting']['device_minus_host_bytes']==4000 and not short['zero_loss_required']
    excess=report(8004);classify(excess)
    assert excess['status']=='failed' and excess['byte_accounting']['state']=='host_excess'
    stale=report();stale['after']['epoch']=1;classify(stale)
    assert stale['status']=='failed'
    usb_error=report();usb_error['after']['usb_failures']=1;classify(usb_error)
    assert usb_error['status']=='failed'
    bw0=report();bw0.update(source='bw0_capture',config={'duration_ms':10000})
    bw0['after'].update(source=2,elapsed_ms=10000,cp_flags=1)
    classify(bw0); assert bw0['status']=='passed' and bw0['requested_duration_reached']
    bw0['after'].update(elapsed_ms=20,cp_flags=3)
    classify(bw0); assert bw0['status']=='failed' and not bw0['requested_duration_reached']
    bw0['after'].update(elapsed_ms=10000,recovery=dict(full_ring_stops=2,attempts=2,completed=2))
    classify(bw0)
    assert bw0['status']=='completed_with_gaps' and bw0['source_interrupted']
    assert not bw0['sustained_source_supply_verified'] and bw0['requested_duration_reached']
    bw0['host']['bytes']=4000; classify(bw0)
    assert bw0['status']=='completed_with_gaps' and bw0['byte_accounting']['device_minus_host_bytes']==4000
    bw0['after']['elapsed_ms']=20;classify(bw0)
    assert bw0['status']=='failed' and not bw0['requested_duration_reached']
    import struct
    class BW0Client:
        def request(self,operation):
            assert operation==44
            words=[0]*48
            for index,value in {0:0x31574353,1:1,2:1,3:4,5:3,6:10000,8:2,9:1920000,
                10:4,11:12,22:8000,36:1,40:40<<8,44:1,45:20,46:10000,47:2000000000}.items(): words[index]=value
            return struct.pack('<48I',*words)
    sample=status(BW0Client(),'bw0')
    assert check_fixed_source_ownership(BW0Client(),bw0_info)['cp_held'] is False
    class HeldCP(BW0Client):
        def __init__(self,active=False):self.calls=[];self.active=active
        def request(self,operation):
            self.calls.append(operation)
            data=bytearray(super().request(operation))
            struct.pack_into('<I',data,3*4,3 if self.active else 4)
            struct.pack_into('<I',data,15*4,0 if self.active else 1)
            return bytes(data)
    for client in (HeldCP(),HeldCP(active=True)):
        try:check_fixed_source_ownership(client,bw0_info)
        except ValueError as error:assert 'no start, stop or reset command sent' in str(error)
        else:raise AssertionError('held or active BW0 service allowed fixed-source startup')
        assert client.calls==[44]
    assert check_fixed_source_ownership(object(),raw_info) is None
    assert sample['bytes']==8000 and sample['source']==2 and sample['elapsed_ms']==10000
    assert sample['worker_active_us'] is None and sample['state']==3
    assert sample['gain_index']==20 and sample['frequency_hz']==2000000000 and sample['band']==40
    assert not sample['iq_mapping_verified']
    class RecoveryClient(BW0Client):
        def request(self,operation):
            if operation!=48: return super().request(operation)
            return struct.pack('<24I',0x31524353,1,3,3,2,2,2,0,250,0,100,150,0,10000,10000,0,1,0,1,3,0,0,0,0)
    sample=status(RecoveryClient(),'bw0',True)
    assert sample['recovery']['full_ring_stops']==2 and sample['recovery']['observed_gap_total_ms']==250
    assert sample['recovery']['gap_is_software_observation'] and not sample['recovery']['lost_samples_known']
    class WrongEpoch(RecoveryClient):
        def request(self,operation):
            data=super().request(operation)
            return data[:8]+struct.pack('<I',2)+data[12:] if operation==48 else data
    try:
        status(WrongEpoch(),'bw0',True)
    except ValueError:
        pass
    else:
        raise AssertionError('mixed user session recovery snapshot accepted')
    class Client:
        def __init__(self): self.calls=[]
        def request(self,operation):
            self.calls.append(operation)
            raise TimeoutError('stop reply missing')
    class Process:
        def __init__(self): self.terminated=False;self.killed=False
        def poll(self): return None
        def terminate(self): self.terminated=True
        def kill(self): self.killed=True
        def wait(self,timeout):
            if not self.killed: raise TimeoutError('terminate wait timed out')
            return 0
    client=Client();process=Process()
    errors=cleanup(client,process,True)
    assert client.calls==[42] and process.terminated and process.killed and len(errors)==2
    client=Client();process=Process();cleanup(client,process,False)
    assert client.calls==[] and process.terminated
    paths=[ROOT/'tools/usb/benchmark.py',ROOT/'tools/usb/native_control.py',Path(__file__)]
    result=dict(status='passed',device_accessed=False,hardware_tested=False,
        scope='benchmark classification, cleanup and native Windows named stop event; no native WinUSB I/O exercised',
        checks=['named event opens with CLI synchronization rights and signals','byte balance','loss reported without zero-loss gate','excess bytes rejected',
            'fixed diagnostic accepts both known images only with exact advertised ABI/operations/source',
            'fixed source refuses held/active BW0 using only status44, never mutates CP or resets',
            'stale epoch rejected','device USB error rejected','uncertain START requires STOP',
            'STOP failure does not skip receiver termination','bounded terminate-to-kill fallback',
            'BW0 status mapping and active timing','early CP full-ring stop is not a duration pass',
            'B40 experimental center envelope separate from B5 and status profile separate from IQ mapping',
            'B3/B8 centers and endpoints accepted; adjacent outside and foreign-route centers rejected',
            'B1/B38/B39/B41 software edges and representative centers accepted; outside edges and B34 rejected',
            'B7/B18/B19/B26 software edges accepted and adjacent outside rejected',
            'recovered session classified with gaps, byte shortfall retained, early duration rejected',
            'separate recovery ABI/session, observed gaps and unknown lost-sample count parsed',
            'raw/report path collision rejected before hardware access','existing raw file rejected',
            'raw file length compared with host bytes without payload processing',
            'host queue loss separate from USB shortfall; writer bytes plus recorded queue drops account for host bytes',
            'unexplained missing file bytes or live writer rejected'],
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    path=ROOT/'records/usb/benchmark-verification.json'
    path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
