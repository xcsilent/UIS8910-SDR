"""Read the existing post-drain CP capture-state export, never MMIO or writes."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

from .rf_catalog import ROOT
from .rf_runtime import stopped


def snapshot(port,cp_build,selector,output):
    import serial
    sys.path.insert(0,str(ROOT/'tools/debug'))
    from uis_debug import Client
    output=Path(output).resolve();build_path=Path(cp_build).resolve()
    if not output.is_relative_to(ROOT) or output.exists() or not output.parent.is_dir():
        raise ValueError('choose a new project output')
    build=json.loads(build_path.read_text(encoding='utf8'))
    if not build.get('experimental_pre_switch') or selector not in (5,6,7):
        raise ValueError('explicit switchable experiment build and PRE5/6/7 are required')
    generation=int(build['generation'],0)
    header=ROOT/'firmware/capture/rxcapt_finite_abi.h';binding=ROOT/'firmware/capture/generated/terminal_binding.h'
    text=header.read_text(encoding='utf8');body=text.split('typedef struct {',1)[1].split('} rxcapt_finite_state_t;',1)[0]
    fields={};size=0
    for name,count in re.findall(r'uint32_t\s+(\w+)(?:\[(\d+)\])?;',body):
        fields[name]=size;size+=4*int(count or 1)
    address=int(re.search(r'#define TERM_STATE_EXPORT (0x[0-9a-f]+)u',binding.read_text())[1],16)
    if size!=107*4 or address!=0x8096f800:raise ValueError('capture export layout changed')
    report=dict(status='starting',recorded_at=datetime.now().astimezone().isoformat(),device_accessed=False,
                read_only=True,rf_transmitted=False,selector=selector,generation=hex(generation))
    try:
        with serial.Serial(port,115200,timeout=.1,write_timeout=5) as transport:
            report['device_accessed']=True;client=Client(transport,5);info=client.info()
            if info.get('bw0_experimental_pre_selectors')!=[5,6,7] or info.get('bw0_experimental_rf_mode')!=5:
                raise ValueError('matching experimental firmware INFO required')
            before=list(struct.unpack('<48I',client.request(44)));stopped(before)
            if ((before[40]>>4)&7)!=selector or before[9]!=0:
                raise ValueError('stopped AP configuration does not match selector / unknown rate')
            progress=struct.unpack('<16I',client.bulk_read(0x8096fec0,64,4))
            if progress[0]!=0x54524d31 or progress[1]!=generation or progress[2]&1 or progress[3]!=30 or progress[4]:
                raise ValueError('CP generation or stopped progress does not match')
            data=client.bulk_read(address,size,4)
            if data!=client.bulk_read(address,size,4):raise ValueError('capture export changed during read')
            after=list(struct.unpack('<48I',client.request(44)));stopped(after)
            if before[5]!=after[5]:raise ValueError('capture epoch changed during read')
            selected={name:struct.unpack_from('<I',data,fields[name])[0] for name in
                ('magic','phase','error','saved_txrx_rx_pre_cfg','configured_rx_pre_cfg','restored_txrx_rx_pre_cfg','rx_bandwidth_index')}
            if (selected['magic']!=0x52434631 or selected['phase']!=6 or selected['error'] or
                selected['rx_bandwidth_index']!=5 or selected['configured_rx_pre_cfg']!=(selector<<8)|8):
                raise ValueError('exported configured PRE or RF mode does not match')
            report.update(status='passed',epoch=after[5],export_address=hex(address),fields=selected)
    except Exception as error:report.update(status='failed',error=str(error))
    paths=(Path(__file__),ROOT/'tools/sdr/rf_runtime.py',ROOT/'tools/debug/uis_debug.py',build_path,header,binding)
    report['dependencies']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    return report
