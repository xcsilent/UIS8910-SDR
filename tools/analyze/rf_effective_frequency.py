"""Normalize retained low/high-route boundary traces to the native arithmetic input.

Effective frequency is a software coefficient input, not a measured VCO/LO.
No device access, register writes or inference of continuous coverage.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lowband', type=Path, required=True)
    parser.add_argument('--high-reference', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    low = json.loads(args.lowband.read_text(encoding='utf8'))
    rows = []
    inputs = [Path(__file__), args.lowband, ROOT/'firmware/rf_rebuild/rf_core_frequency.c']

    def append(band, center, outcome, capture, trace, evidence):
        phase = next(r for r in trace if r['stage'] == 'before_rf_stop')
        working = phase['working_raw']
        effective = working*2 if working < 10000000 else working
        factor = phase['context_factor_b526']
        assert factor > 0
        rows.append(dict(band=band, center_hz=center, outcome=outcome, capture=capture,
            working_hz=working*100, coefficient_input_hz=effective*100,
            arithmetic_doubled=working < 10000000, factor=factor,
            q8=(effective*256//260000)&65535,
            fraction=(effective*(1<<28)//(260000*factor))&0xffffffff,
            selector=phase['selector'], rx_port=phase['rx_port'],
            rxpll_vco_bits=phase['rxpll_vco_bits_reference'],
            rxpll_cal_ready=phase['rxpll_cal_ready_reference'], evidence=evidence))

    for row in low['rows']:
        for trace in row['traces']:
            if trace['capture'] == 'tone150':
                append(low['band'], row['center_hz'], row['status'], trace['capture'],
                       trace['records'], args.lowband.as_posix())
    for path in args.high_reference:
        report = json.loads(path.read_text(encoding='utf8'))
        trace_path = path.with_name(path.stem+'-tone150-rf-status.json')
        capture_path = path.with_name(path.stem+'-tone150.json')
        trace = json.loads(trace_path.read_text(encoding='utf8'))
        capture = json.loads(capture_path.read_text(encoding='utf8'))
        append(capture['config']['band'], capture['config']['frequency_hz'], report['status'],
               'tone150', trace['records'], trace_path.as_posix())
        inputs.extend([path, trace_path, capture_path])
    assert len(rows) >= 4
    result = dict(status='completed', device_accessed=False, firmware_changed=False, rows=rows,
        scope='Derived from recorded before-stop RAM/status and native coefficient formula. Different firmware generations, routes and experiment dates; not a matched RF comparison.',
        interpretation=[
            'Low-route frequency doubling places its lower reception transition near the high-route transition in coefficient-input space; examine rows numerically.',
            'This raises a shared PLL/LO-domain hypothesis across different RX ports. It does not prove a shared physical cutoff or exclude board filters.',
            'Successful and missing references both have very low VCO codes and ready high. Neither field independently identifies RF lock.',
            'Coefficient-input Hz is not measured VCO Hz, and MDLL factor is not a proven output divider.'
        ],
        next='Prefer tracing actual LO/output-divider and calibration consumers over unchanged sweeps or arbitrary filter/reset writes. A matched same-effective-frequency cross-route test is useful only with current identity/reference and a specific competing hypothesis.',
        dependencies={p.resolve().relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')
    print(json.dumps(dict(status='completed', rows=[{k:r[k] for k in ('band','center_hz','outcome','coefficient_input_hz','rxpll_vco_bits')} for r in rows])))


if __name__ == '__main__':
    main()
