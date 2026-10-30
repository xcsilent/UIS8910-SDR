"""Derive publication tables/figures from retained final records, without hardware.

Only JSON summaries and source metadata are read. IQ payloads are never read or
hashed. --check checks deterministic tables; figures require matplotlib.
"""
import argparse
import csv
import io
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'docs/data'
ASSETS = ROOT / 'docs/assets'


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8-sig'))


def csv_text(rows, columns):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def derive():
    sources = {
        'passband_bw01': 'records/rf/bw01-summary.json',
        'passband_bw2': 'records/rf/mainline-bw2-passband-refined.json',
        'passband_bw34': 'records/rf/wideband-passband-fft-summary.json',
        'passband_bw5': 'records/usb/geometry-v20-bw5-passband-summary.json',
        'rf_grid_upper': 'records/rf/coverage-b40-grid-2400-2800-summary.json',
        'rf_grid_lower': 'records/rf/coverage-b40-grid-2000-2390-summary.json',
        'communication': 'records/communication/functional-acceptance.json',
        'registers': 'records/rf/reference-rf-register-crosswalk.json',
        'firmware': 'outputs/firmware/current/manifest.json',
        'host': 'outputs/host/manifest.json',
    }
    original = {k: read(v) for k, v in sources.items()}
    widths = {int(k): v for k, v in original['passband_bw01']['final_width_brackets_hz'].items()}
    widths[2] = original['passband_bw2']['total_minus3db_width_bracket_hz']
    for row in original['passband_bw34']['rows']:
        widths[row['bandwidth_index']] = row['relative_minus3db_width_bracket_hz']
    widths[5] = original['passband_bw5']['total_relative_minus3db_width_bracket_hz']
    modes = []
    for bw, rate in enumerate((1920000, 3840000, 7680000, 15360000, 30720000, 30720000)):
        seconds = 10 if bw <= 2 else 3
        key = 'usb_bw' + str(bw)
        sources[key] = f'records/usb/b8-880-bw{bw}-{seconds}s-v29-20261029.json'
        usb = read(sources[key])
        modes.append({
            'bandwidth_index': bw, 'nominal_complex_sample_rate_hz': rate,
            'full_raw_bytes_per_second': rate * 4,
            'historical_relative_minus3db_total_width_hz': widths[bw],
            'passband_route': 40 if bw == 5 else 5,
            'passband_source': sources['passband_bw01' if bw < 2 else 'passband_bw2' if bw == 2 else 'passband_bw34' if bw < 5 else 'passband_bw5'],
            'passband_rf_signal_hz': 2000150000 if bw == 5 else 881650000,
            'passband_rx_gain_index': 40,
            'passband_tx_gain_setting': 20 if bw < 2 else 40,
            'steady_device_bytes_per_second': usb['steady_device_bytes_per_second'],
            'usb_measurement_duration_ms': usb['duration_ms'],
            'usb_host_received_bytes': usb['host_bytes'],
            'usb_device_completed_bytes': usb['device_completed_bytes'],
            'usb_device_minus_host_bytes': usb['device_minus_host_bytes'],
            'usb_drained': usb['device_drained'], 'usb_source': sources[key],
            'streaming_scope': 'budget_sustainable_not_proven_gap_free' if bw < 2 else 'borderline_no_sustained_margin' if bw == 2 else 'partial_output_with_unlocated_gaps',
        })
    upper = original['rf_grid_upper']
    lower = original['rf_grid_lower']
    assert len(upper['grid']) == upper['grid_points']
    assert sum(r['acceptance'] == 'complete_reference' for r in upper['grid']) == upper['complete_reference_points']
    grid = [{'frequency_hz': f, 'acceptance': 'complete_reference',
             'source': sources['rf_grid_lower']} for f in range(lower['first_hz'], lower['last_hz'] + 1, lower['step_hz'])]
    assert len(grid) == lower['points'] == lower['verified_points']
    grid += [{'frequency_hz': row['frequency_hz'], 'acceptance': row['acceptance'],
              'source': sources['rf_grid_upper']} for row in upper['grid']]
    communication = []
    keys = ('record', 'frequency_hz', 'modulation', 'bandwidth_index', 'duration_s',
            'sample_rate_hz', 'frames', 'ber', 'evm_rms', 'realtime_host_passed',
            'pipe_dropped_bytes', 'pipe_gap_events', 'host_cpu_seconds',
            'native_receiver_cpu_seconds', 'receiver_elapsed_seconds',
            'device_minus_host_bytes', 'tx_gain_setting_db', 'rx_gain_index',
            'source_peak', 'iq_amplitude', 'source_file_accounting',
            'device_drained', 'all_children_released')
    for row in original['communication']['rows']:
        communication.append({k: row[k] for k in keys})
    crosswalk = original['registers']
    registers, fields = [], []
    for row in crosswalk['registers']:
        registers.append({
            'rf_local': row['rf_local'], 'cp_view': row['cp_view'],
            'kind': row['kind'], 'reference_block': row.get('block', ''),
            'reference_name': row.get('reference_name') or '',
            'trace_observed': row['trace_read'],
            'trace_abis': ','.join(str(x) for x in row['trace_abis']),
            'source_mentions': ';'.join(x['source'] + (':' + str(x['line']) if 'line' in x else '') for x in row['uses']),
            'scope': 'declaration_or_software_reference_not_hardware_write_authorization',
        })
        for field in row.get('fields', []):
            fields.append({'rf_local': row['rf_local'], 'reference_name': row.get('reference_name') or '',
                           **{k: field[k] for k in ('name', 'lsb', 'width', 'mask')},
                           'scope': 'ZW217_reference_declaration_not_independent_silicon_validation'})
    assert len(registers) == crosswalk['counts']['crosswalk_entries']
    result = {
        'schema_version': 1, 'snapshot_date': '2026-10-30',
        'scope': 'Derived from final historical records, not a new device measurement or continuous RF specification.',
        'hardware': 'Air724UG / UIS8910DM; one RX channel; receive only',
        'firmware_generation': original['firmware']['installed_firmware']['running_generation'],
        'numeric_format': {'raw_order': 'lane0,lane1', 'container': 'little_endian_signed_int16',
                           'native_bits_per_lane': 12, 'valid_container_bits': '15:4',
                           'bytes_per_complex_sample': 4,
                           'host_cf32': '(lane0-j*lane1)/2048 after arithmetic int16>>4',
                           'physical_iq_labels_verified': False, 'enob': None},
        'frequency': {
            'engineering_envelopes_hz': [[687500000, 1000000000], [1375000000, 2786000000]],
            'continuous_coverage_verified': False, 'chip_physical_limits_hz': None,
            'lowband_caveat': '1000 MHz is a software envelope. References at970/985/990 MHz;995 weak;999.9 not identified;1000 communication failed.',
            'grid_points': grid, 'upper_boundary': upper['additional_boundary_points'],
            'highest_complete_upper_reference_center_hz': upper['highest_complete_reference_center_hz'],
        },
        'bandwidth_modes': modes,
        'communication_10s': communication,
        'register_crosswalk_counts': crosswalk['counts'],
        'exported_named_field_rows': len(fields),
        'unknowns': ['continuous_frequency_coverage', 'chip_physical_frequency_limits', 'RF_LO_lock_field',
                     'exact_external_frontend_part_and_board_wiring', 'ENOB', 'calibrated_absolute_power',
                     'noise_figure', 'IIP3', 'SFDR', 'sample_clock_ppm', 'exact_lost_samples',
                     'absolute_sample_timestamps', 'phase_continuity'],
        'sources': sources,
        'raw_payload_read_or_hashed': False,
    }
    return {
        'sdr-capabilities.json': json.dumps(result, ensure_ascii=False, indent=2) + '\n',
        'rf-registers.csv': csv_text(registers, list(registers[0])),
        'rf-fields.csv': csv_text(fields, list(fields[0])),
    }, result


def figures(data):
    cache = ROOT / 'work/report-matplotlib-cache'
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('MPLCONFIGDIR', str(cache))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'svg.fonttype': 'none'})
    ASSETS.mkdir(parents=True, exist_ok=True)
    modes = data['bandwidth_modes']
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7), layout='constrained')
    x = np.arange(6)
    axes[0].bar(x - .18, [r['full_raw_bytes_per_second']/1e6 for r in modes], width=.36, label='Full raw budget (4 B/complex)', color='#326da8')
    axes[0].bar(x + .18, [r['steady_device_bytes_per_second']/1e6 for r in modes], width=.36, label='Historical device completion rate', color='#289782')
    axes[0].axhspan(30, 32, alpha=.14, color='#d4862b')
    axes[0].set(xticks=x, xticklabels=[f'BW{i}' for i in x], ylabel='MB/s (decimal)', title='USB budget versus observed supply')
    axes[0].legend(fontsize=8, loc='upper left')
    for i, row in enumerate(modes):
        lo, hi = [v/1e6 for v in row['historical_relative_minus3db_total_width_hz']]
        axes[1].plot([i, i], [lo, hi], color='#326da8', linewidth=4)
        axes[1].scatter([i], [(lo+hi)/2], color='#326da8', s=25)
        axes[1].annotate(f'{lo:g}–{hi:g}', (i, hi), xytext=(0, 7), textcoords='offset points', ha='center', fontsize=8)
    axes[1].set(xticks=x, xticklabels=[f'BW{i}' for i in x], ylabel='Total relative −3 dB width (MHz)', ylim=(0, 21), title='Historical end-to-end response brackets')
    for ax in axes:
        ax.spines[['top', 'right']].set_visible(False)
        ax.grid(axis='y', alpha=.18)
    fig.suptitle('UIS8910 SDR: nominal rates, historical measurements and limits', fontsize=13)
    fig.supxlabel('USB: B8 / 880 MHz, v29, 10 s (BW0–2), 3 s (BW3–5). Response: B5 (BW0–4), B40 (BW5).\nUncalibrated; different firmware generations. Completion rate does not prove gap-free acquisition.', fontsize=8)
    for suffix in ('svg', 'png'):
        fig.savefig(ASSETS / ('bandwidth-usb.' + suffix), dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(12, 3.8), layout='constrained')
    styles = {
        'complete_reference': ('#168474', 'o', 'Complete reference'),
        'user_accepted_environment_affected': ('#c48a24', '^', 'User-accepted interference affected'),
    }
    other = set(r['acceptance'] for r in data['frequency']['grid_points']) - set(styles)
    for key in other:
        styles[key] = ('#aa5261', 'x', key.replace('_', ' '))
    for key, (color, marker, label) in styles.items():
        points = [r['frequency_hz']/1e6 for r in data['frequency']['grid_points'] if r['acceptance'] == key]
        if points:
            ax.scatter(points, [0 if key == 'complete_reference' else 1]*len(points), color=color, marker=marker, s=22, label=label)
    ax.set(xlabel='Receiver center frequency (MHz)', yticks=[0, 1], yticklabels=['Complete reference', 'Conditional / incomplete'], ylim=(-.65, 2.0), title='B40 historical grid evidence — measured points only')
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis='x', alpha=.2)
    ax.legend(loc='upper center', ncol=2, fontsize=8)
    fig.supxlabel('2000–2390 MHz: 10 MHz grid, 40/40 complete. 2400–2800 MHz: 5 MHz grid, 72/81 complete.\nNo interpolation, continuous-coverage claim, sensitivity calibration or chip-limit inference.', fontsize=8)
    for suffix in ('svg', 'png'):
        fig.savefig(ASSETS / ('rf-grid.' + suffix), dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='compare derived tables only; no matplotlib required')
    parser.add_argument('--figures', action='store_true', help='also generate SVG/PNG figures from the same summaries')
    args = parser.parse_args()
    tables, data = derive()
    if args.check:
        mismatch = [name for name, content in tables.items() if not (DATA/name).is_file() or (DATA/name).read_text(encoding='utf-8') != content]
        print(json.dumps({'status': 'failed' if mismatch else 'passed', 'mismatched_tables': mismatch, 'device_accessed': False}))
        return int(bool(mismatch))
    DATA.mkdir(parents=True, exist_ok=True)
    for name, content in tables.items():
        (DATA/name).write_text(content, encoding='utf-8', newline='\n')
    if args.figures:
        figures(data)
    print(json.dumps({'status': 'generated', 'tables': list(tables), 'figures': args.figures, 'device_accessed': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
