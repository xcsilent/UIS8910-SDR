#!/usr/bin/env python3
"""Recover a held or stalled CP CALL using a byte-verified AP AT reset path."""
import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

import serial

from uis_debug import BASELINE, Client

ROOT = Path(__file__).resolve().parents[2]
IMAGE = ROOT / 'inputs/firmware/build-baseline/8915DM_cat1_CSDK.img'
IMAGE_SHA = 'a53750880d595e8f54bbb0c8cd5a43fcbce1bba3c67b8b01acb4a1d244dc4a27'
SUPPORTED_FIRMWARE = ('uis8910-debug-v2-bulk', 'uis8910-rxcapt-service-v1', 'uis8910-rxcapt-stream-v2', 'uis8910-rxcapt-stream-v3', 'uis8910-rxcapt-stream-v4')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def monitor(port):
    return serial.Serial(port, 115200, timeout=.1, write_timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--monitor-port', default='COM9')
    parser.add_argument('--at-port', default='COM7')
    parser.add_argument('--recovery-seconds', type=float, default=20)
    args = parser.parse_args()
    require(5 <= args.recovery_seconds <= 60, 'recovery timeout outside 5..60 seconds')
    folder = ROOT / 'records/host/runtime-recovery'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('at-recovery-' + datetime.now().strftime('%Y%m%dT%H%M%S') + '.json')
    report = {'started': datetime.now().astimezone().isoformat(), 'status': 'running',
              'monitor_port': args.monitor_port, 'at_port': args.at_port,
              'firmware_flashed': False, 'cp_requests_sent': False, 'reset_sent': False,
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    try:
        image = IMAGE.read_bytes()
        require(hashlib.sha256(image).hexdigest() == IMAGE_SHA, 'archived AP image changed')
        with monitor(args.monitor_port) as port:
            client = Client(port, 2)
            report['info_before'] = client.info()
            require(report['info_before'].get('firmware') in SUPPORTED_FIRMWARE and
                    report['info_before'].get('cp_baseline_sha256') == BASELINE, 'monitor identity differs')
            first = client.status()
            time.sleep(.3)
            last = client.status()
            report['status_before'] = [first, last]
            require(last['pending'] and last['request_seq'] != last['response_seq'] and
                    first['heartbeat'] == last['heartbeat'],
                    'CP CALL is not proven held or stalled; no reset sent')
            report['ap_code_checks'] = []
            for name, address, size in (('atCmdHandleRESET', 0x6002f95c, 48),
                                         ('osiShutdown', 0x600f9e80, 204)):
                raw = client.read('ap', 'flash', address, size, 4)
                expected = image[address - 0x60010000:address - 0x60010000 + size]
                row = {'name': name, 'address': hex(address), 'bytes': size, 'match': raw == expected,
                       'sha256': hashlib.sha256(raw).hexdigest()}
                report['ap_code_checks'].append(row)
                require(row['match'], 'AP reset code differs: ' + name)
        save()
        with monitor(args.at_port) as port:
            port.write(b'AT\r\n')
            raw = bytearray()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and b'\r\nOK\r\n' not in raw:
                raw.extend(port.read(max(1, port.in_waiting)))
            report['at_probe_hex'] = raw.hex()
            require(b'\r\nOK\r\n' in raw, 'independent AP AT port did not respond')
            port.write(b'AT+RESET\r\n')
            report['reset_sent'] = True
            save()
            raw = bytearray()
            deadline = time.monotonic() + 2
            try:
                while time.monotonic() < deadline:
                    raw.extend(port.read(max(1, port.in_waiting)))
            except OSError as error:
                report['expected_disconnect'] = str(error)
            report['reset_reply_hex'] = raw.hex()
        deadline = time.monotonic() + args.recovery_seconds
        report['recovery_observations'] = []
        recovered = False
        while time.monotonic() < deadline:
            try:
                with monitor(args.monitor_port) as port:
                    client = Client(port, 1)
                    info = client.info()
                    first = client.status()
                    time.sleep(.25)
                    last = client.status()
                    require(info.get('firmware') == report['info_before']['firmware'] and
                            info.get('cp_baseline_sha256') == BASELINE and info.get('cp_agent_ready') and
                            info.get('bulk_read'), 'monitor not yet ready')
                    if info['firmware'] == 'uis8910-rxcapt-service-v1':
                        require(info.get('rxcapt_resident_ready') and
                                info.get('rxcapt_resident_status') == 0,
                                'receiver resident preload failed after reset')
                    require(first['heartbeat'] != last['heartbeat'] and not last['pending'] and
                            last['request_seq'] == last['response_seq'] and not last['cp_status'] and
                            not last['active_entry'] and not last['previous_entry'], 'CP not reset and idle')
                    report['info_after'] = info
                    report['status_after'] = [first, last]
                    recovered = True
                    break
            except (OSError, RuntimeError) as error:
                report['recovery_observations'].append(str(error))
                time.sleep(.25)
        require(recovered, 'AP reset recovery was not verified before deadline')
        report['status'] = 'recovered'
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = str(error)
    finally:
        report['finished'] = datetime.now().astimezone().isoformat()
        save()
    print(json.dumps({'status': report['status'], 'reset_sent': report['reset_sent'],
                      'record': path.relative_to(ROOT).as_posix(), 'error': report.get('error')}, indent=2))
    return 0 if report['status'] == 'recovered' else 1


if __name__ == '__main__':
    raise SystemExit(main())
