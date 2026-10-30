"""Compare a retained RF boundary pair without transmitting or changing hardware.

Request-chain evidence uses the SDK image and synthetic MMIO. Check the relevant
current PAC bodies/tables and execute its mode helper before reusing that scope.
This cannot establish filter bypass, RF lock, or a chip frequency limit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/verify'))
from rf_image import current_pac_image
from verify_rf_mode_native import run


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-chain', type=Path, required=True)
    parser.add_argument('--coefficients', type=Path, required=True)
    parser.add_argument('--band', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    chain = json.loads(args.request_chain.read_text(encoding='utf8'))
    coefficients = json.loads(args.coefficients.read_text(encoding='utf8'))
    assert chain['status'] == coefficients['status'] == 'passed'
    # Do not summarize a stale native report as current execution evidence.
    for report in (chain, coefficients):
        for name, digest in report['dependencies'].items():
            assert sha(ROOT/name) == digest, name
    image_path, provenance = current_pac_image()
    current = image_path.read_bytes()
    assert coefficients['image_source'] == 'current PAC decoded payload'
    assert coefficients['image_sha256'] == sha(image_path)
    sdk = ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin/riscV.bin'
    reference = sdk.read_bytes()
    rows = [r for r in chain['retained_board_route_chain']['rows'] if r['raw_band_id'] == args.band]
    assert len(rows) == 1 and rows[0]['group'] == 'B'
    row = rows[0]
    # Exact, limited equivalence checks. Entry/correction code differs between
    # PAC and SDK; it is deliberately not labeled byte-identical here.
    ranges = [('B RXON body', 0x4ecc, 0x5360),
              ('port analog rows', 0x8a54, 0x8aa4),
              ('port route table', 0x8184, 0x8194),
              ('post-RX code prefix', 0x38a8, 0x39a0)]
    byte_checks = []
    for name, start, end in ranges:
        same = current[start:end] == reference[start:end]
        assert same, name
        byte_checks.append(dict(name=name, start=hex(start), end_exclusive=hex(end), equal=same))
    header = ROOT/'inputs/reference-source/riscv-pulp-legacy/riscv-opc.h'
    manifest = header.with_name('source-manifest.json')
    assert sha(header) == next(f['sha256'] for f in json.loads(manifest.read_text())['files'] if f['file'] == header.name)
    definitions = {k:int(v,16) for k,v in re.findall(r'#define\s+((?:MATCH|MASK)_\w+)\s+(0x[0-9a-fA-F]+)', header.read_text())}
    pairs = [('EXTHZ','PALUS'),('BCLR','PALU2'),('BNEM1','BNEM1'),('BEQM1','BEQM1'),
             ('LHUPOST','LPOST'),('SHPOST','SPOST'),('LWRR','LRR')]
    rules = [(name,definitions['MATCH_'+name],definitions['MASK_'+mask]) for name,mask in pairs]
    mode_checks = []
    for mode in range(6):
        actual = run(current, rules, mode, 0, 0, selector=row['selector'])
        expected = run(reference, rules, mode, 0, 0, selector=row['selector'])
        assert actual['writes'] == expected['writes']
        mode_checks.append(dict(mode=mode, ordered_writes=len(actual['writes']), equal=True))
    comparisons = row['paired_frequency_mmio_differences']
    assert comparisons
    coefficient_addresses = {'0x30360', '0x302c4', '0x302c8'}
    for comparison in comparisons:
        comparison['differences_outside_frequency_words'] = [d for d in comparison['value_differences']
                                                             if d['address'] not in coefficient_addresses]
        comparison['same_nonfrequency_mmio_writes'] = (comparison['same_ordered_addresses_and_widths'] and
                                                       not comparison['differences_outside_frequency_words'])
    inputs = [Path(__file__), args.request_chain, args.coefficients, sdk, image_path,
              header, manifest, ROOT/'tools/verify/verify_rf_mode_native.py', *provenance]
    result = dict(status='passed', device_accessed=False, firmware_changed=False,
        band=args.band, selector=row['selector'], rx_port=row['rx_port'],
        byte_equivalence=byte_checks, mode_helper_equivalence=mode_checks,
        comparisons=comparisons, current_pac_coefficients=args.coefficients.as_posix(),
        scope='Offline native B request fixture and current-PAC coefficient/mode checks. Not live RAM, full boot, caller entry equivalence, or analog response.',
        conclusion='For this retained pair, inspect same_nonfrequency_mmio_writes per mode. Equality means no software filter/route switch in the tested B body; a fixed analog response or LO failure is not excluded.',
        next='Avoid toggling unnamed filter/reset bits. Trace an independently identified LO/analog control or integrate already verified coverage into delivered hosts.',
        dependencies={p.resolve().relative_to(ROOT).as_posix():sha(p) for p in dict.fromkeys(inputs)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')
    print(json.dumps(dict(status='passed', comparisons=len(comparisons),
                         same_nonfrequency_mmio_writes=all(c['same_nonfrequency_mmio_writes'] for c in comparisons))))


if __name__ == '__main__':
    main()
