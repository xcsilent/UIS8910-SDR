"""Bounded read-only snapshot of runtime RF frontend configuration."""
from datetime import datetime
import hashlib,json,struct,sys
from .rf_catalog import ROOT
from .rf_runtime import RFNV,stopped
BYTES=16384
MIPI={'switch_open':0x310,'switch_close':0x490,'lna_open':0x610,'lna_close':0x790}
GPO={'switch_open':0x1428,'switch_close':0x1488,'lna_open':0x14e8,'lna_close':0x1548,'rxtx':0x17e8}

def decode_row(nv,row,antenna):
    if len(nv)!=BYTES or not 0<=row<24 or not 0<=antenna<4:raise ValueError('frontend requires16384bytes, row0..23, antenna0..3')
    mipi={name:[dict(zip(('reg_value','reg_addr','slave_id','reserved'),nv[offset+16*row+4*i:offset+16*row+4*i+4])) for i in range(4)] for name,offset in MIPI.items()}
    gpo={name:dict(zip(('mask','value'),struct.unpack_from('<2H',nv,offset+4*row))) for name,offset in GPO.items()}
    gpo['antenna']=dict(zip(('mask','value'),struct.unpack_from('<2H',nv,0x1910+4*antenna)))
    mask=value=0
    for name in ('switch_open','lna_open','rxtx','antenna'):mask|=gpo[name]['mask'];value|=gpo[name]['value']
    return dict(nv_row=row,band_id=struct.unpack_from('<H',nv,0x20+2*row)[0],
        rx_port=struct.unpack_from('<H',nv,0xf0+4*row)[0],antenna_row=antenna,mipi=mipi,gpo=gpo,
        mdll_enable=struct.unpack_from('<H',nv,0x1270)[0],mdll_table_value=struct.unpack_from('<H',nv,0x1274+2*row)[0],
        gpo_open_command=0x440000|((value|(mask<<8))&65535))

def frontend(args):
    output=args.output.resolve();binary=output.with_suffix('.rfnv.bin')
    if not output.is_relative_to(ROOT) or output.exists() or binary.exists() or not output.parent.is_dir():raise ValueError('choose new project JSON/binary paths in an existing directory')
    import serial
    sys.path.insert(0,str(ROOT/'tools/debug'));from uis_debug import Client
    report=dict(recorded_at=datetime.now().astimezone().isoformat(),status='starting',device_accessed=False,read_only=True,
        firmware_changed=False,calibration_written=False,RF_settings_changed=False,physical_reception_verified=False,
        scope='runtime NV configuration only; no MIPI/GPO bus waveform or physical filter/LNA identification')
    with output.open('x',encoding='utf-8') as stream:
        try:
            with serial.Serial(args.port,115200,timeout=.1,write_timeout=5) as port:
                client=Client(port,5);report['device_accessed']=True;report['firmware']=info=client.info()
                if info.get('firmware')!='uis8910-sdr-bw0-usb-v1' or info.get('cp_baseline_sha256')!='bd25923aa2fd2cde32fafe59305b6655a79645ad7ff447b74f0ffd4286a020d1' or not info.get('bulk_read'):
                    raise ValueError('unsupported identity; fixed NV address not used')
                before=list(struct.unpack('<48I',client.request(44)));stopped(before)
                nv=client.bulk_read(RFNV,BYTES,2)
                if nv!=client.bulk_read(RFNV,BYTES,2):raise ValueError('runtime NV changed between reads')
                after=list(struct.unpack('<48I',client.request(44)));stopped(after)
                if before!=after:raise ValueError('receiver status changed during read-only snapshot')
                rows=[decode_row(nv,i,a) for i in range(24) for a in range(4)]
                binary.write_bytes(nv)
                report.update(status='passed',status_before=before,status_after=after,epoch=after[5],stable_repeated_reads=True,
                    rows=rows,artifacts=[dict(path=binary.relative_to(ROOT).as_posix(),bytes=BYTES,address=hex(RFNV),sha256=hashlib.sha256(nv).hexdigest())])
        except Exception as error:report.update(status='failed',error=str(error))
        report['dependencies']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ('tools/sdr/rf_frontend.py','tools/sdr/rf_runtime.py','tools/debug/uis_debug.py','firmware/rf_rebuild/rf_frontend_nv.c','firmware/rf_rebuild/rf_frontend_nv.h')}
        json.dump(report,stream,indent=2);stream.write('\n')
    return report
