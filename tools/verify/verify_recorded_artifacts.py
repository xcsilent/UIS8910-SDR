"""Check metadata relocation and intentional IQ deletion without replaying IQ."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from sdr.artifacts import recorded_file


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def numeric_values(value, trail=()):
    if isinstance(value, dict):
        return {p: n for k, v in value.items()
                for p, n in numeric_values(v, trail + (k,)).items()}
    if isinstance(value, list):
        return {p: n for i, v in enumerate(value)
                for p, n in numeric_values(v, trail + (i,)).items()}
    return {trail: (type(value).__name__, value)} if isinstance(value, (int, float)) else {}


def check():
    retention = read('records/retention/retention.json')
    assert retention['raw_payloads_retained'] is False
    audit = read(retention['audit'])
    assert audit['applied'] and not audit['errors']
    assert audit['removed_files'] == audit['planned_files']
    for row in audit['files']:
        assert not (ROOT / row['path']).exists(), row['path']
    original_iq = read('records/retention/manifest.json')['relocations']
    for value in (*original_iq, *(r['path'] for r in original_iq.values())):
        try:
            recorded_file(value)
        except FileNotFoundError as error:
            assert 'intentionally removed' in str(error), value
        else:
            raise AssertionError('removed IQ resolved to replacement: ' + value)
    for value in ('../outside-project.raw', ROOT.parent / 'outside-project.raw'):
        try:
            recorded_file(value)
        except ValueError:
            pass
        else:
            raise AssertionError('accepted outside-project path')
    locations = read('records/index.json') if (ROOT / 'records/index.json').is_file() else {}
    moves = locations.get('relocations', {})
    for old, new in moves.items():
        target = (ROOT / new).resolve()
        assert target.is_file(), new
        assert recorded_file(old) == target, old
        assert recorded_file(ROOT / old) == target, old
    archive_info = {'available': False, 'scope': 'Local metadata archive optional in public source exports.'}
    archive = ROOT / locations.get('archive', 'unavailable-metadata.zip')
    if archive.is_file():
        with zipfile.ZipFile(archive) as saved:
            assert saved.testzip() is None
            index = json.loads(saved.read('ARCHIVE-INDEX.json'))
            assert len(index) == len(saved.namelist()) - 1
            for row in index:
                data = saved.read(row['path'])
                assert len(data) == row['bytes']
                assert hashlib.sha256(data).hexdigest() == row['sha256'], row['path']
            archived_only = next(r['path'] for r in index
                                 if r['path'].startswith('records/') and r['path'] not in moves)
            try:
                recorded_file(archived_only)
            except FileNotFoundError as error:
                assert locations['archive'] in str(error) and archived_only in str(error)
            else:
                raise AssertionError('archived-only metadata silently restored')
            checked_json = 0
            checked_binary = 0
            for old, new in moves.items():
                if not old.startswith('records/'):
                    continue
                if old.endswith('.json'):
                    before = json.loads(saved.read(old))
                    after = read(new)
                    old_numbers = {tuple(moves.get(k, k) if isinstance(k, str) else k
                                         for k in path): value
                                   for path, value in numeric_values(before).items()}
                    assert old_numbers == numeric_values(after), new
                    checked_json += 1
                elif old.endswith('.bin'):
                    assert saved.read(old) == (ROOT / new).read_bytes(), new
                    checked_binary += 1
            archive_info = dict(available=True, zip_integrity=True,
                                member_hashes_verified=len(index),
                                retained_json_numeric_values_unchanged=checked_json,
                                retained_context_binaries_unchanged=checked_binary,
                                archived_only_rejected_with_location=True)
    return dict(status='passed', device_accessed=False, payload_available=False,
                payload_hashed=False, spectra_recomputed=False,
                removed_files=audit['removed_files'], removed_bytes=audit['removed_bytes'],
                exact_relocations_verified=len(moves), outside_project_rejected=True,
                metadata_archive=archive_info,
                scope='Metadata integrity, exact relocation and authorized IQ deletion only; no new RF or firmware test.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = check()
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
