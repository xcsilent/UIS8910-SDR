"""Portable offline checks for source-review documentation and final metadata.

No SDK, binary build, hardware, network or third-party Python dependency. This
does not certify licenses, RF performance or full-workstation reproducibility.
"""
import ast
import csv
import io
import json
from pathlib import Path
import re
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ('README.md', 'README.zh-CN.md', 'CONTRIBUTING.md', 'LICENSE-STATUS.md',
           'THIRD_PARTY_NOTICES.md', 'docs/README.md', 'docs/technical-report.md',
           'docs/technical-report.en.md', 'docs/performance.md', 'docs/architecture.md',
           'docs/register-reference.md', 'docs/getting-started.md', 'docs/building.md',
           'docs/maintainer-review.md', 'docs/project-structure.md')


def check():
    from generate_report_assets import derive
    tables, caps = derive()
    for name, expected in tables.items():
        assert (ROOT/'docs/data'/name).read_text(encoding='utf-8') == expected, 'stale derived table: ' + name
    assert len(list(csv.DictReader(io.StringIO(tables['rf-registers.csv'])))) == caps['register_crosswalk_counts']['crosswalk_entries']
    for row in caps['bandwidth_modes']:
        assert row['full_raw_bytes_per_second'] == 4*row['nominal_complex_sample_rate_hz']
        assert row['usb_device_completed_bytes'] - row['usb_host_received_bytes'] == row['usb_device_minus_host_bytes']
    policy = json.loads((ROOT/'docs/publication-manifest.json').read_text(encoding='utf-8'))
    assert '.pac' not in policy['allowed_suffixes'] and '.dll' not in policy['allowed_suffixes']
    for name in policy['individual_files']:
        assert (ROOT/name).is_file(), 'missing allowlisted file: ' + name
    selected = set(policy['individual_files']) | set(caps['sources'].values())
    selected.update(row['record'] for row in caps['communication_10s'])
    for prefix in policy['source_directories']:
        selected.update(p.relative_to(ROOT).as_posix() for p in (ROOT/prefix).rglob('*')
                        if p.is_file() and p.suffix.lower() in policy['allowed_suffixes'] and '__pycache__' not in p.parts)
    for source in caps['sources'].values():
        assert (ROOT/source).is_file(), 'missing final summary: ' + source
    documents = set(PRIMARY)
    for prefix in policy['source_directories']:
        documents.update(p.relative_to(ROOT).as_posix() for p in (ROOT/prefix).rglob('*.md'))
    links = 0
    external = []
    for name in sorted(documents):
        p = ROOT/name
        body = p.read_text(encoding='utf-8-sig')
        assert body.count('```') % 2 == 0, 'unclosed code fence: ' + name
        for target in re.findall(r'\]\(([^)]+)\)', body):
            target = target.strip('<>').split('#', 1)[0]
            if not target or '://' in target or target.startswith('mailto:'):
                continue
            resolved = (p.parent/unquote(target)).resolve()
            assert resolved.is_relative_to(ROOT), 'escaping link: ' + name
            relative = resolved.relative_to(ROOT).as_posix()
            if not resolved.exists():
                # A review export intentionally excludes full historical inputs.
                # Never accept a missing source/doc/asset or an allowlisted record.
                assert relative not in selected and relative.startswith(('records/', 'outputs/', 'inputs/', 'archive/', 'work/')), 'broken primary link: ' + name + ' -> ' + target
                external.append({'document': name, 'local_only_reference': relative})
            links += 1
    syntax = list((ROOT/'tools').rglob('*.py'))
    for p in syntax:
        ast.parse(p.read_text(encoding='utf-8-sig'), filename=p.relative_to(ROOT).as_posix())
    for figure in ('bandwidth-usb', 'rf-grid'):
        for suffix in ('svg', 'png'):
            assert (ROOT/'docs/assets'/(figure+'.'+suffix)).stat().st_size > 1000
    retention = json.loads((ROOT/'records/retention/retention.json').read_text(encoding='utf-8'))
    assert retention['raw_payloads_retained'] is False
    return {'status': 'passed', 'scope': 'portable docs/final-table consistency and Python syntax only',
            'device_accessed': False, 'documents': len(documents), 'local_links': links,
            'python_syntax_files': len(syntax), 'register_rows': caps['register_crosswalk_counts']['crosswalk_entries'],
            'external_local_references': external, 'RF_retested': False, 'license_certified': False}


def main():
    try:
        result = check()
    except (AssertionError, ValueError, KeyError, OSError, SyntaxError) as error:
        result = {'status': 'failed', 'error': str(error), 'device_accessed': False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
