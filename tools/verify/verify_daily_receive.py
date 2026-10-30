"""Native daily capture wrapper against the already verified fake-device CLI."""
import copy,hashlib,json,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from sdr.receive import receive,summarize

def main():
    cli=ROOT/'work/host-file-sink-test/file_cli_test.exe'
    prior=ROOT/'records/usb/host-file-verification.json'
    record=json.loads(prior.read_text())
    key=cli.relative_to(ROOT).as_posix()
    assert hashlib.sha256(cli.read_bytes()).hexdigest()==record['dependencies'][key]
    build=ROOT/'work/daily-receive-test';build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=build) as temporary:
        directory=Path(temporary)
        for bw in (0,1,2):
            args=SimpleNamespace(port='COM99',band=5,frequency_hz=881500000,gain_index=40,
                bandwidth_index=bw,milliseconds=100,requests=8,request_bytes=65536,
                file_queue_blocks=32,sync_file=False,iq_output=directory/f'bw{bw}.raw',output=directory/f'bw{bw}.json')
            report=receive(args,executable=cli)
            assert report['status']=='passed',report
            assert report['transport_completed'] and report['requested_duration_reached']
            assert report['raw_file']['bytes']==1024 and not report['raw_file']['payload_inspected']
            assert report['format']['sample_rate_nominal_hz']==1920000<<bw
            assert not report['format']['sample_rate_measured'] and not report['sustained_source_supply_verified']
            assert json.loads(args.output.read_text())==report
            try:receive(args,executable=cli)
            except ValueError:pass
            else:raise AssertionError('existing files accepted')
            # Metadata-only classifier: allowed loss, interrupted source, wrong
            # epoch, early completion and missing file bytes remain distinct.
            loss=copy.deepcopy(report);h=loss['host'];h['device_status'][22]+=8000
            summarize(loss);assert loss['status']=='completed_with_loss'
            gaps=copy.deepcopy(report);gaps['host']['recovery_status'][4]=1
            summarize(gaps);assert gaps['status']=='completed_with_gaps' and not gaps['sustained_source_supply_verified']
            both=copy.deepcopy(gaps);both['host']['device_status'][22]+=8000
            summarize(both);assert both['status']=='completed_with_gaps' and both['source_interrupted']
            assert both['byte_accounting']['host_shortfall_observed'] is True
            assert both['byte_accounting']['shortfall_cause']=='unknown'
            wrong=copy.deepcopy(report);wrong['host']['device_status'][5]+=1
            summarize(wrong);assert wrong['status']=='failed' and wrong['byte_accounting']['device_completed_bytes'] is None
            assert wrong['byte_accounting']['host_shortfall_observed'] is None
            early=copy.deepcopy(report);early['host']['device_status'][46]=1
            summarize(early);assert early['status']=='failed'
            early['interrupted_by_user']=True;summarize(early);assert early['status']=='stopped_by_user'
            missing=copy.deepcopy(report);missing['host']['file_written_bytes']+=4
            summarize(missing,args.iq_output);assert missing['status']=='failed'
            steady=copy.deepcopy(report)
            steady['config']['duration_ms']=3000;steady['host']['device_status'][46]=3000
            steady['host'].update(steady_device_rate_measured=True,steady_device_counter_invalid=False,
                steady_device_bytes_per_second=(1920000<<bw)*4,steady_device_samples=8,steady_device_window_ms=2000)
            summarize(steady);assert steady['sustained_source_supply_verified']
            steady['host']['recovery_status'][4]=1
            summarize(steady);assert not steady['sustained_source_supply_verified']
            steady['host']['recovery_status'][4]=0;steady['host']['steady_device_counter_invalid']=True
            summarize(steady);assert not steady['steady_throughput_measured']
        args.milliseconds=0;args.output=directory/'continuous.json';args.iq_output=directory/'continuous.raw'
        continuous=receive(args,executable=cli)
        assert continuous['status']=='passed' and continuous['continuous_mode'] and continuous['transport_completed'],continuous
        assert not continuous['requested_duration_reached'] and continuous['host']['stop_requested']
        assert continuous['raw_file']['bytes']==1024
        expired=copy.deepcopy(continuous);expired['host']['recovery_status'][21]=1
        summarize(expired);assert expired['status']=='failed'
        unexpected=copy.deepcopy(continuous);unexpected['host']['stop_requested']=False
        summarize(unexpected);assert unexpected['status']=='failed'
        args.output=directory/'new.json';args.iq_output=args.output
        try:receive(args,executable=cli)
        except ValueError:pass
        else:raise AssertionError('raw/JSON collision accepted')
        assert not args.output.exists()
    dependencies=[Path(__file__),ROOT/'tools/sdr/receive.py',ROOT/'tools/sdr.py',ROOT/'tools/sdr/rf_catalog.py',cli,prior]
    result=dict(status='passed',device_accessed=False,hardware_tested=False,
        scope='actual native fake-device CLI -> daily wrapper -> raw file length and JSON metadata; no real USB/RF',
        tests=['BW0/BW1/BW2 native subprocess capture','exclusive raw/report paths','native result and saved JSON agreement',
               'loss and source gaps distinguished','wrong epoch not reused','early completion rejected; user stop distinguished',
               'unexplained file length rejected','IQ payload never read by wrapper',
               'supply assessment requires measured interval and no source interruption; counter reset invalidates it',
               'actual continuous CLI stops explicitly, flushes raw tail; expired lease and unsolicited terminal fail'],
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies})
    (ROOT/'records/usb/daily-receive-verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
