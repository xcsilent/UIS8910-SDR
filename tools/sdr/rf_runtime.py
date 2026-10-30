"""Bounded read-only RF snapshot for the identified, stopped receiver service.

No CP calls, NV writes, capture start, reset or firmware deployment. The snapshot
is point-in-time evidence, never a live capability cache for a later session.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import struct
import sys

from .rf_catalog import ROOT, catalog

RFNV = 0x804f42b8
TABLE = 0x8047190e
REMAP = {18: 5, 19: 5, 26: 5, 25: 2, 45: 61, 59: 62}


def stopped(words):
    if len(words) != 48 or words[:2] != [0x31574353, 1]:
        raise ValueError('unsupported receiver status layout')
    # phase4 is the retained CP service after completed STOP/drain. Generic
    # monitor pending is expected there; it is not evidence of a stalled CP.
    if not (words[3] == 4 and words[4] == 0 and words[12] == 3 and
            words[26] == 0 and words[30] and words[37] and words[34] == words[35]):
        raise ValueError('receiver must already be stopped, DMA idle and drained; snapshot never stops it')


def decode(nv, tables):
    if len(nv) != 0x180 or len(tables) != 7 * 54:
        raise ValueError('incomplete RF NV/table snapshot')
    bands = struct.unpack_from('<24H', nv, 0x20)
    arrays = [struct.unpack_from('<27H', tables, i * 54) for i in range(7)]
    # Preserve the actual post-NV IDs/order; selector evidence must match IDs.
    selectors = {r['raw_band_id']: r['sdk_default_routing']['selector'] for r in catalog()['rows']}
    rows = []
    for i, band in enumerate(arrays[0]):
        wanted = REMAP.get(band, band)
        matches = [j for j, value in enumerate(bands) if value == wanted and wanted]
        if len(matches) > 1:
            raise ValueError('ambiguous duplicate NV band entries')
        nv_row = matches[0] if matches else None
        low, high = arrays[1][i], arrays[2][i]
        # Native fdllow units are100kHz. Runtime changed noffs is authoritative;
        # the other arrays include middle channel and uplink frequency data.
        first = arrays[4][i] * 100000
        rows.append(dict(table_row=i, raw_band_id=band, channel_first=low,
            channel_last=high, first_center_hz=first,
            last_center_hz=first + (high-low)*100000,
            required_nv_band_id=wanted, nv_row=nv_row,
            rx_port=struct.unpack_from('<H', nv, 0xf0+4*nv_row)[0] if nv_row is not None else None,
            selector_from_native_evidence=selectors.get(band),
            calibration_entry_present=nv_row is not None,
            physical_reception_verified=False))
    return dict(nv_bands=list(bands),
        nv_rx_tx_ports=[list(struct.unpack_from('<2H', nv, 0xf0+4*i)) for i in range(24)],
        nv_flags=[struct.unpack_from('<H', nv, 0x52+4*i)[0] for i in range(24)],
        eesf=bool(struct.unpack_from('<H', nv, 0x176)[0] & 0x4000), rows=rows)


def snapshot(port, output):
    import serial
    sys.path.insert(0, str(ROOT/'tools/debug'))
    from uis_debug import Client
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT) or output.exists() or not output.parent.is_dir():
        raise ValueError('choose a new JSON report in an existing directory')
    nv_path = output.with_suffix('.rfnv.bin')
    table_path = output.with_suffix('.tables.bin')
    if nv_path.exists() or table_path.exists():
        raise ValueError('snapshot binary paths already exist')
    report = dict(recorded_at=datetime.now().astimezone().isoformat(),
        status='starting', device_accessed=False, read_only=True,
        firmware_changed=False, calibration_written=False, physical_reception_verified=False,
        port=port, protocol='existing AP RAM bulk snapshot operation32',
        scope='point-in-time runtime calibration presence and mutable channel table; no physical range claim')
    with output.open('x', encoding='utf-8') as stream:
        try:
            with serial.Serial(port, 115200, timeout=.1, write_timeout=5) as transport:
                report['device_accessed'] = True
                client = Client(transport, 5)
                info = client.info()
                report['firmware'] = info
                if (info.get('firmware') != 'uis8910-sdr-bw0-usb-v1' or
                        info.get('cp_baseline_sha256') != 'bd25923aa2fd2cde32fafe59305b6655a79645ad7ff447b74f0ffd4286a020d1' or
                        not info.get('bulk_read') or not info.get('bw0_usb')):
                    raise ValueError('unsupported firmware/baseline; fixed addresses not used')
                def status():
                    body = client.request(44)
                    if len(body) != 192:
                        raise ValueError('unexpected receiver status size')
                    return list(struct.unpack('<48I', body))
                before = status()
                stopped(before)
                nv = client.bulk_read(RFNV, 0x180, 2)
                tables = client.bulk_read(TABLE, 378, 2)
                # A serial snapshot is not atomic across regions. Re-read both
                # small, inactive regions and check the epoch to reject changes.
                if nv != client.bulk_read(RFNV, 0x180, 2) or tables != client.bulk_read(TABLE, 378, 2):
                    raise ValueError('RF data changed during snapshot')
                after = status()
                stopped(after)
                if before[5] != after[5]:
                    raise ValueError('receiver epoch changed during snapshot')
                report.update(status_before=before, status_after=after,
                    stable_repeated_reads=True, epoch=after[5], **decode(nv, tables))
                nv_path.write_bytes(nv)
                table_path.write_bytes(tables)
                report['artifacts'] = [dict(path=p.relative_to(ROOT).as_posix(),
                    sha256=hashlib.sha256(p.read_bytes()).hexdigest(), address=hex(a))
                    for p, a in ((nv_path, RFNV), (table_path, TABLE))]
                report['status'] = 'passed'
        except Exception as error:
            report.update(status='failed', error=str(error))
        report['dependencies'] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
            for name in ('tools/sdr/rf_runtime.py', 'tools/sdr/rf_catalog.py',
                         'tools/debug/uis_debug.py', 'records/usb/rf-channel-routes.json')}
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return report
