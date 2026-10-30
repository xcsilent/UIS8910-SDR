"""Build and run native Windows writer/CLI tests without accessing USB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'records/usb/host-file-verification.json')
    args=parser.parse_args()
    cross=ROOT/'work/windows-toolchain/root/usr'
    environment=dict(os.environ)
    environment['PATH']=str(cross/'bin')+os.pathsep+environment.get('PATH','')
    build=ROOT/'work/host-file-sink-test'
    build.mkdir(parents=True,exist_ok=True)
    common=[str(cross/'bin/x86_64-w64-mingw32-gcc-posix'),'-std=c11','-O2','-Wall','-Wextra','-Werror','-static-libgcc']
    harness=ROOT/'tools/verify/host_file_sink_harness.c'
    cli_harness=ROOT/'tools/verify/host_file_cli_harness.c'
    sink=ROOT/'host/windows/file_sink.c'
    exe=build/'file_sink_test.exe';cli=build/'file_cli_test.exe'
    subprocess.run(common+[str(harness),'-o',str(exe)],env=environment,check=True)
    session=ROOT/'host/windows/sdr_session.c';info=ROOT/'host/windows/sdr_info.c'
    profile=ROOT/'firmware/capture/rxcapt_profile.c'
    subprocess.run(common+[str(cli_harness),str(sink),str(session),str(info),str(profile),'-o',str(cli)],env=environment,check=True)
    with tempfile.TemporaryDirectory(dir=build) as temporary:
        windows=subprocess.check_output(['wslpath','-w',temporary],text=True).strip()
        result=subprocess.check_output([str(exe),windows],text=True,timeout=20).strip()
        for mode in ('queued','synchronous','bw0','bw1','bw2'):
            output=Path(temporary)/(mode+'.raw')
            command=[str(cli),'--output',windows+'\\'+output.name]
            if mode=='synchronous': command+=['--sync-file']
            is_capture=mode.startswith('bw')
            if is_capture: command+=['--port','COM99','--milliseconds','100','--bandwidth-index',mode[-1]]
            run=subprocess.run(command,check=True,capture_output=True,text=True,timeout=10)
            stats=json.loads(run.stdout)
            assert (is_capture or 'ready' in run.stderr) and stats['bytes']==1024 and stats['file_written_bytes']==1024
            assert stats['file_mode']==('queued' if is_capture else mode) and not stats['file_error'] and not stats['file_dropped_bytes']
            if is_capture:
                assert stats['device_drained'] and stats['device_completed_bytes']==1024 and stats['device_minus_host_bytes']==0
                assert not stats['control_error'] and not stats['cleanup_error'] and stats['epoch']==7
                assert stats['bandwidth_index']==int(mode[-1]) and not stats['sample_rate_measured']
            assert not stats['file_writer_alive'] and not stats['file_pending_blocks']
            assert output.read_bytes()==bytes(j%256 for j in range(512))+bytes((j+1)%256 for j in range(512))
        # Byte-exact pipe output, including NUL/newline/high bytes. JSON must
        # never be interleaved with the IQ stream, even for controlled sessions.
        for controlled in (False,True):
            command=[str(cli),'--stdout-raw']
            if controlled:command+=['--port','COM99','--milliseconds','100']
            run=subprocess.run(command,check=True,capture_output=True,timeout=10)
            expected=bytes(j%256 for j in range(512))+bytes((j+1)%256 for j in range(512))
            assert run.stdout==expected
            stats=json.loads(run.stderr.decode().splitlines()[-1])
            assert stats['bytes']==len(expected) and not stats['file_error']
            if controlled:assert stats['device_drained'] and stats['device_minus_host_bytes']==0
        rejected=subprocess.run([str(cli),'--stdout-raw','--output','forbidden.raw'],capture_output=True)
        assert rejected.returncode==2 and not rejected.stdout
    dependencies=[Path(__file__),harness,cli_harness,sink,session,info,profile,ROOT/'host/common/rf_auto.h',ROOT/'host/windows/sdr_session.h',ROOT/'host/windows/file_sink.h',ROOT/'host/windows/sdr_receive.c',ROOT/'host/windows/sdr_usb.h',cli]
    report=dict(status='passed',device_accessed=False,hardware_tested=False,result=result,
        scope='native Windows threads/events/files with controlled WriteFile latency/failures; actual CLI with stub USB, queued and synchronous raw bytes compared; no WinUSB/device throughput proof',
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies})
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
