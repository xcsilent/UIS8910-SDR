"""Summarize captured stream geometry and recovery; no hardware or RF claim."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--slot-bytes', type=int, required=True)
    parser.add_argument('--slots', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    p = json.loads(args.capture.read_text(encoding='utf-8'))
    host = p['host']
    rate = p['format']['sample_rate_nominal_hz'] * p['format']['bytes_per_complex_sample']
    gap = host['observed_gap_ms']
    stops = host['full_ring_stops']
    assert args.slot_bytes > 0 and args.slots > 0 and rate > 0 and stops > 0
    result = {
        'status': 'observations_recorded', 'capture': str(args.capture).replace('\\', '/'),
        'nominal_bytes_per_second': rate, 'slot_bytes': args.slot_bytes,
        'slots': args.slots, 'nominal_empty_ring_fill_ms': args.slots * args.slot_bytes / rate * 1000,
        'observed_gap_ms': gap, 'full_ring_stops': stops,
        'observed_gap_ms_per_full_stop': gap / stops,
        'steady_device_bytes_per_second': host['steady_device_bytes_per_second'],
        'nominal_rate_is_measured': p['format']['sample_rate_measured'],
        'interpretation': 'Empty-ring fill is ideal arithmetic with no simultaneous draining; gap-per-stop is a ratio of aggregate counters, not a measured distribution. Neither proves an individual bottleneck or exact missing samples.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
