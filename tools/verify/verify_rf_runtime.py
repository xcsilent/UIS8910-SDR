"""RF snapshot decoding and refusal guards; no device access."""
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from sdr.rf_runtime import decode, stopped


def main():
    inventory = json.loads((ROOT/'records/usb/rf-channel-inventory.json').read_text())
    cp = (ROOT/inventory['cp_path']).read_bytes()
    start = inventory['band_id_table_file_offset']
    tables = cp[start:start+378]
    nv = bytearray(0x180)
    struct.pack_into('<24H', nv, 0x20, 1,0,3,0,5,7,8,0,0,0,0,38,39,0,0,0,0,0,0,0,0,0,40,41)
    rows = decode(nv, tables)['rows']
    for expected, actual in zip(inventory['rows'], rows):
        assert (expected['raw_band_id'], expected['dl_first_hz'], expected['dl_last_hz']) == (
            actual['raw_band_id'], actual['first_center_hz'], actual['last_center_hz'])
    by_band = {r['raw_band_id']: r for r in rows}
    assert by_band[7]['nv_row'] == 5 and by_band[34]['nv_row'] is None
    assert all(by_band[b]['nv_row'] == 4 for b in (5,18,19,26))
    # A different runtime layout changes matches, never silently reuses a row.
    struct.pack_into('<H', nv, 0x20+2*5, 0)
    struct.pack_into('<H', nv, 0x20+2*13, 34)
    struct.pack_into('<H', nv, 0xf0+4*13, 1)
    moved = {r['raw_band_id']: r for r in decode(nv,tables)['rows']}
    assert moved[7]['nv_row'] is None and moved[34]['nv_row'] == 13 and moved[34]['rx_port'] == 1
    good = [0]*48
    good[:2] = [0x31574353,1]
    good[3] = 4; good[12] = 3; good[30] = 1; good[37] = 1
    stopped(good)
    cases = 0
    for index, value in ((0,0),(3,2),(4,1),(12,2),(26,1),(30,0),(37,0),(34,1)):
        bad = good.copy(); bad[index] = value
        try: stopped(bad)
        except ValueError: cases += 1
        else: raise AssertionError('unsafe state accepted')
    for n, t in ((nv[:-1],tables),(nv,tables[:-1])):
        try: decode(n,t)
        except ValueError: cases += 1
        else: raise AssertionError('truncated snapshot accepted')
    struct.pack_into('<H', nv, 0x20+2, 34)
    try: decode(nv,tables)
    except ValueError: cases += 1
    else: raise AssertionError('duplicate calibration match accepted')
    dependencies = [Path(__file__), ROOT/'tools/sdr/rf_runtime.py', ROOT/'tools/sdr/rf_catalog.py',
        ROOT/'records/usb/rf-channel-inventory.json', ROOT/inventory['cp_path']]
    report = dict(status='passed', device_accessed=False, native_rows_checked=len(rows),
        rejected_unsafe_or_malformed_cases=cases,
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies})
    (ROOT/'records/rf/runtime-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__': main()
