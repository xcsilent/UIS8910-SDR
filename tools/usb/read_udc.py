"""Read current 720U UDC objects through the AP monitor; never change USB state."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import struct
import sys

import serial

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/debug'))
from uis_debug import Client


def snapshot(port, abi_path):
    abi = json.loads(abi_path.read_text(encoding='utf-8'))
    state = json.loads((ROOT/'docs/project-state.json').read_text(encoding='utf-8'))
    if abi['pac_sha256'] != state['installed_firmware']['sha256']:
        raise ValueError('UDC analysis is for a different installed PAC')
    queue = next(f for f in abi['functions'] if f['name'] == 'prvDwcEpQueue')
    if not queue['same_address_pac_bytes_match']:
        raise ValueError('SDK/PAC UDC code did not match')
    with serial.Serial(port, 115200, timeout=0.05, write_timeout=3) as connection:
        client = Client(connection, timeout=3)
        info = client.info()
        if (info['firmware'] != state['installed_firmware']['identity'] or
                info['cp_baseline_sha256'] != state['installed_firmware']['cp_baseline_sha256']):
            raise ValueError('live monitor identity differs')
        prefix = client.read('ap', 'flash', int(queue['address'], 16)&~1, 24, 4)
        if prefix.hex() != queue['sdk_prefix']:
            raise ValueError('live UDC queue signature differs')

        def read(address, length):
            if not 0x80989f60 <= address < address+length <= 0x81000000 or address&3 or length&3:
                raise ValueError(f'UDC object outside AP RAM: {address:#x}+{length}')
            return b''.join(client.read('ap', 'ram', address+i, min(1024, length-i), 4)
                            for i in range(0, length, 1024))

        device = struct.unpack('<I', read(0x809b6c70, 4))[0]
        drv = read(device, 72)
        udc_address, cops = struct.unpack_from('<II', drv, 28)
        udc = read(udc_address, 100)
        enqueue, private = struct.unpack_from('<I', udc, 44)[0], struct.unpack_from('<I', udc, 92)[0]
        if enqueue != int(queue['address'], 16):
            raise ValueError('live UDC operation pointer differs')
        dwc = read(private, 1160)
        if struct.unpack_from('<II', dwc) != (udc_address, 0x09040000):
            raise ValueError('DWC back pointer/register base differs')
        endpoints = []
        for direction, base, count in [('in', 8, dwc[944]), ('out', 476, dwc[945])]:
            if count > 13:
                raise ValueError('DWC endpoint count exceeds ABI array')
            for index in range(count):
                offset = base+index*36
                endpoints.append(dict(direction=direction, index=index, object=hex(private+offset),
                    address=hex(dwc[offset]), mps=struct.unpack_from('<H', dwc, offset+2)[0],
                    flags=hex(dwc[offset+8]), dma_max=struct.unpack_from('<I', dwc, offset+12)[0],
                    active_request=hex(struct.unpack_from('<I', dwc, offset+20)[0]),
                    queue_first=hex(struct.unpack_from('<I', dwc, offset+24)[0])))
        return dict(recorded_at=datetime.now().astimezone().isoformat(), read_only=True,
            usb_resets=0, device=hex(device), udc=hex(udc_address), composite=hex(cops),
            controller_private=hex(private), controller_speed=struct.unpack_from('<I', udc)[0],
            queue_entry=hex(enqueue), queue_prefix_matches=True,
            in_endpoint_count=dwc[944], out_endpoint_count=dwc[945], endpoints=endpoints,
            monitor=info, cp_status=client.status(), raw_transport_hardware_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--abi', type=Path, default=ROOT/'records/usb/udc-abi.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        parser.error('choose a new output path inside the project')
    report = snapshot(args.port, args.abi)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
