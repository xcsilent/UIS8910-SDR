"""Experimental stopped-only FEM template mode, separate from raw IQ."""
import hashlib,json,struct,sys
from datetime import datetime
from pathlib import Path
from .rf_catalog import ROOT

def decode(data):
    if len(data)!=16:raise ValueError('invalid FEM control length')
    magic,abi,mode,epoch=struct.unpack('<4I',data)
    if (magic,abi)!=(0x314d4546,1) or mode>2:raise ValueError('invalid FEM control identity/mode')
    return dict(abi=abi,mode=mode,register_value={0:None,1:2,2:5}[mode],epoch=epoch,
        meaning='next B5/B8 capture template; not live external-chip readback')

def configure(args):
    output=args.output.resolve()
    if not output.is_relative_to(ROOT) or output.exists() or not output.parent.is_dir():
        raise ValueError('choose a new project output in an existing directory')
    import serial
    sys.path.insert(0,str(ROOT/'tools/debug'));from uis_debug import Client
    report=dict(recorded_at=datetime.now().astimezone().isoformat(),status='starting',device_accessed=False,
        requested_value=args.value,firmware_flashed=False,rf_transmitted=False,
        scope='Diagnostic next-capture command-template selection only. No ACK, identity or reception proof.')
    try:
        with serial.Serial(args.port,115200,timeout=.1,write_timeout=5) as port:
            client=Client(port,5);report['device_accessed']=True;report['firmware']=info=client.info()
            if info.get('firmware')!='uis8910-sdr-bw0-usb-v1' or info.get('bw0_fem_override_operation')!=53 or info.get('bw0_fem_override_abi')!=1:
                raise ValueError('firmware does not advertise FEM operation53/ABI1; no FEM request sent')
            report['before']=decode(client.request(53))
            if args.value is not None:
                mode={'default':0,'2':1,'5':2}[args.value]
                report['configuration_attempted']=True
                report['reply']=decode(client.request(53,struct.pack('<2I',1,mode)))
                report['after']=decode(client.request(53))
                if report['reply']['mode']!=mode or report['after']['mode']!=mode:
                    raise ValueError('FEM mode readback mismatch; do not start another experiment')
            report['status']='passed'
    except Exception as error:report.update(status='failed',error=str(error))
    paths=[Path(__file__),ROOT/'tools/debug/uis_debug.py']
    report['dependencies']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report
