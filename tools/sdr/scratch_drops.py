"""Read final experimental scratch-drop count via the separate control path."""
from datetime import datetime
import hashlib
import json
import struct
import sys
from .rf_catalog import ROOT


def transact(client, report):
    info = client.info()
    report['firmware'] = info
    if (info.get('firmware') != 'uis8910-sdr-bw0-usb-v1' or
        info.get('bw0_scratch_drops_operation') != 52 or info.get('bw0_scratch_drops_abi') != 1):
        raise ValueError('firmware does not advertise scratch-drop operation 52 ABI 1; no request sent')
    report['operation_sent'] = True
    data = client.request(52)
    if len(data) != 16:
        raise ValueError('invalid scratch-drop reply length')
    magic, version, epoch, count = struct.unpack('<4I', data)
    if magic != 0x31504453 or version != 1 or not epoch:
        raise ValueError('invalid scratch-drop reply ABI or epoch')
    report.update(epoch=epoch, discarded_complete_pairs=count, counter_saturated=count==0xffffffff,
                  exact_lost_samples_known=False,
                  scope='Stopped and drained session only; complete scratch pairs, not all lost samples.')


def read(args):
    output = args.output.resolve()
    if not output.is_relative_to(ROOT) or output.exists() or not output.parent.is_dir():
        raise ValueError('choose a new project report in an existing directory')
    import serial
    sys.path.insert(0, str(ROOT/'tools/debug'))
    from uis_debug import Client
    report = dict(recorded_at=datetime.now().astimezone().isoformat(),status='starting',
                  device_accessed=False,read_only=True,operation_sent=False)
    with output.open('x',encoding='utf-8') as stream:
        try:
            with serial.Serial(args.port,115200,timeout=.1) as port:
                report['device_accessed']=True
                transact(Client(port,5),report)
                report['status']='passed'
        except Exception as error:
            report.update(status='failed',error=str(error))
        report['dependencies']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
                                for p in ('tools/sdr/scratch_drops.py','tools/debug/uis_debug.py')}
        json.dump(report,stream,indent=2);stream.write('\n')
    return report
