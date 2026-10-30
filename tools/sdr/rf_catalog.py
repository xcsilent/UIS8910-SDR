"""Offline RF catalog derived from current C profiles and retained evidence.

Never opens hardware. Software envelopes, native table rows, calibration evidence
and physical reception are distinct; the latter is not inferred from the former.
"""
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
INPUTS=('firmware/capture/rxcapt_profile.c','firmware/sdr_receiver/rf_profile.h',
        'records/usb/rf-channel-inventory.json',
        'records/usb/rf-channel-routes.json',
        'records/usb/rf-nv-source-comparison.json',
        'records/rf/coverage-v32-b3-lower-summary.json')

def read(name):
    return json.loads((ROOT/name).read_text(encoding='utf-8'))

def validate_b3_floor(hz):
    if hz is not None and (type(hz) is not int or hz%100 or not 1650000000<=hz<1710000000):
        raise ValueError('experimental B3 floor must be in [1650,1710) MHz in 100 Hz units')
    return hz


def software_profiles(experimental_b3_min_hz=None,unrestricted_frequency=False):
    """Single C table drives AP/CP, build advertisements and host adapters."""
    validate_b3_floor(experimental_b3_min_hz)
    text=(ROOT/INPUTS[0]).read_text(encoding='utf-8')
    table=re.search(r'profiles\[\]\s*=\s*\{(.*?)\n\};',text,re.S)
    if not table:
        raise ValueError('current C profile table shape changed; update catalog extraction')
    entries=re.findall(r'\{\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)u,\s*(\d+)u,\s*(\d+)u\s*\}',table[1])
    if len(entries)!=table[1].count('{'):
        raise ValueError('unrecognized C profile row; refusing incomplete catalog')
    implemented={}
    for entry in entries:
        band,low,high,anchor,minimum,maximum=map(int,entry)
        if band in implemented or low>high or minimum>maximum:
            raise ValueError('invalid or duplicate software profile')
        implemented[band]=dict(minimum_hz=minimum*100,maximum_hz=maximum*100,
            anchor_channel_first=low,anchor_channel_last=high,anchor_first_hz=anchor*100,
            anchor_policy='fixed' if low==high else 'floor_100khz_clamped',request_step_hz=100)
    if experimental_b3_min_hz is not None:
        implemented[3]['minimum_hz']=experimental_b3_min_hz
    if unrestricted_frequency:
        for profile in implemented.values():
            profile.update(minimum_hz=100,maximum_hz=4294967200)
    return implemented


def catalog(experimental_b3_min_hz=None,unrestricted_frequency=False):
    inventory=read(INPUTS[2])['rows']
    routes={r['raw_band_id']:r for r in read(INPUTS[3])['rows']}
    comparisons=read(INPUTS[4])['native_selector_checks']
    nv={s['source']:{r['raw_band_id']:r['native_nv_row'] for r in s['tests']} for s in comparisons}
    implemented=software_profiles(experimental_b3_min_hz,unrestricted_frequency)
    b3_points=read(INPUTS[5])['points']
    for band,p in implemented.items():
        low,high=p['anchor_channel_first'],p['anchor_channel_last']
        rows=[r for r in inventory if r['channel_first']<=low<=high<=r['channel_last']]
        if len(rows)!=1 or rows[0]['raw_band_id']!=band:
            raise ValueError('initialization anchor has no unique native table row')
    result=[]
    for row in inventory:
        band=row['raw_band_id'];route=routes[band]
        observations=route['observations']
        routing={key:observations[0][key] for key in ('nv_row','selector','rx_port')}
        matches={source:values.get(band) for source,values in nv.items()}
        result.append(dict(raw_band_id=band,table_row=row['row'],
            native_table=dict(channel_first=row['channel_first'],channel_last=row['channel_last'],
                minimum_hz=row['dl_first_hz'],maximum_hz=row['dl_last_hz']),
            software_integrated=band in implemented,software_profile=implemented.get(band),
            sdk_default_routing=routing,calibration_rows_by_recorded_source=matches,
            runtime_calibration_verified=False,physical_receive_interval_hz=None,
            reference_points=([dict(frequency_hz=p['frequency_hz'],status=p['status'],record=p['record'])
                               for p in b3_points] if band==3 else []),
            module_advertised_band=row['module_advertised_band'],
            remaining_dependency=('runtime INFO/profile and NV gate, then RF reference validation' if band in implemented else
                'profile integration with matching runtime calibration; native table alone is insufficient')))
    return dict(device_accessed=False,scope='offline current software and recorded native/NV evidence; no live capability assertion',
        format=dict(numeric_bits_per_lane=12,storage_bytes_per_complex_sample=4,bandwidth_index=0,
                    nominal_sample_rate_hz=1920000,iq_mapping_verified=False),
        rows=result,notes=['raw IDs are not all confirmed 3GPP band numbers',
            'B40 experiment envelope includes failed and degraded edges; not continuous verified coverage',
            'historical board calibration is not current runtime calibration',
            'software request step is not measured tuning resolution'])

def plan_receive(band,*,frequency_hz,gain_index=40,experimental_b3_min_hz=None,unrestricted_frequency=False):
    if any(type(v) is not int for v in (band,frequency_hz,gain_index)):
        raise ValueError('band, frequency_hz and gain_index must be integers')
    if not 0<=gain_index<=124:
        raise ValueError('gain_index must be 0..124, not a calibrated dB value')
    row=next((r for r in catalog(experimental_b3_min_hz,unrestricted_frequency)['rows'] if r['raw_band_id']==band),None)
    if row is None or not row['software_integrated']:
        raise ValueError('requested raw band has no current BW0 software profile; inspect rf-catalog')
    p=row['software_profile']
    if frequency_hz%100 or not p['minimum_hz']<=frequency_hz<=p['maximum_hz']:
        raise ValueError('frequency is outside the software experiment envelope or not in 100 Hz request units')
    channel=p['anchor_channel_first']
    if p['anchor_policy']!='fixed':
        channel=max(channel,min(p['anchor_channel_last'],channel+(frequency_hz-p['anchor_first_hz'])//100000))
    anchor=p['anchor_first_hz']+(channel-p['anchor_channel_first'])*100000
    return dict(device_accessed=False,band=band,bandwidth_index=0,
        configure_operation=47,configure_words=[1,band,frequency_hz,gain_index],
        initialization_channel=channel,initialization_frequency_hz=anchor,
        requested_frequency_hz=frequency_hz,frequency_raw=frequency_hz//100,
        software_profile=p,sdk_default_routing=row['sdk_default_routing'],
        calibration_rows_by_recorded_source=row['calibration_rows_by_recorded_source'],
        runtime_capability_verified=False,physical_receive_interval_hz=None,
        scope='offline BW0 precapture configuration; verify INFO and runtime NV before use; no physical limit claim')
