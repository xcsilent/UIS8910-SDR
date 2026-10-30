"""Validate the retained capture layout, including optional RF trace storage.

This checks declared address ranges only. It does not establish DMA reachability,
cache coherence, or USB packet completion behavior on hardware.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def define(text, name):
    match = re.search(r'^\s*#define\s+' + re.escape(name) + r'\s+(0x[0-9a-fA-F]+|[0-9]+)u?\s*$', text, re.M)
    if not match:
        raise ValueError('missing numeric layout define: ' + name)
    return int(match.group(1), 0)


def validate(data_base, slot_bytes, slots, capture_end, stream_address, trace_address=None, trace_bytes=0,
             reserved=()):
    if not slots or not slot_bytes or slot_bytes != (capture_end + 1) * 4:
        raise ValueError('capture bytes and RXCAPT end address disagree')
    data_end = data_base + slot_bytes * slots
    if data_end > stream_address:
        raise ValueError('capture data overlaps stream ownership state')
    if trace_address is not None and data_base < trace_address + trace_bytes and trace_address < data_end:
        raise ValueError('capture data overlaps RF status trace')
    if trace_address is not None and trace_address + trace_bytes > stream_address:
        raise ValueError('RF status trace overlaps stream ownership state')
    for name, address, size in reserved:
        if size <= 0:
            raise ValueError('invalid reserved region: ' + name)
        if data_base < address + size and address < data_end:
            raise ValueError('capture data overlaps ' + name)
        if trace_address is not None and trace_address < address + size and address < trace_address + trace_bytes:
            raise ValueError('RF status trace overlaps ' + name)
    return {'data_base': data_base, 'data_end': data_end, 'slot_bytes': slot_bytes,
            'slots': slots, 'capture_end': capture_end, 'stream_address': stream_address,
            'trace_address': trace_address, 'trace_bytes': trace_bytes}


def current():
    abi = (ROOT / 'firmware/capture/rxcapt_finite_abi.h').read_text(encoding='utf-8')
    ring = (ROOT / 'firmware/capture/rxcapt_ring_resident.c').read_text(encoding='utf-8')
    trace = (ROOT / 'firmware/capture/rxcapt_rf_status_trace.h').read_text(encoding='utf-8')
    recipe = json.loads((ROOT / 'firmware/capture/build-recipe.json').read_text(encoding='utf-8'))
    definitions = [v for v in recipe['commands'][0] if isinstance(v, str)]
    def command_define(name):
        prefix = '-D' + name + '='
        values = [v[len(prefix):].rstrip('uU') for v in definitions if v.startswith(prefix)]
        if len(values) != 1:
            raise ValueError('missing or duplicate recipe definition: ' + name)
        return int(values[0], 0)
    def enabled(name):
        prefix = '-D' + name + '='
        values = [v[len(prefix):].rstrip('uU') for v in definitions if v.startswith(prefix)]
        if len(values) > 1:
            raise ValueError('duplicate recipe definition: ' + name)
        return bool(int(values[0], 0)) if values else False
    reserved = []
    if enabled('RXCAPT_FAST_TUNE'):
        reserved.append(('fast tune trace', 0x8096e000, 128))
    if enabled('RXCAPT_STREAM_TIMING'):
        reserved.append(('stream timing trace', 0x8096e000, 288))
    if enabled('RXCAPT_DIGITAL_PROFILE_TRACE'):
        reserved.append(('digital profile', 0x8096e200, 64))
    return validate(define(ring, 'RXCAPT_RING_DATA_BASE'), define(abi, 'RXCAPT_FINITE_DATA_BYTES'),
                    command_define('RXCAPT_RING_BLOCKS'), define(abi, 'RXCAPT_FINITE_CAPTURE_END_ADDRESS'),
                    command_define('RXCAPT_STREAM_STATE_ADDRESS'), define(trace, 'RF_STATUS_TRACE_ADDRESS'), 512,
                    reserved=reserved)
