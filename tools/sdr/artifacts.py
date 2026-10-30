"""Resolve retained metadata locations from historical reports.

The exact relocation ledger preserves report contents without recreating old
work trees. This is for offline reads, never deployment or hardware commands.
"""
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def recorded_file(value):
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('recorded artifact escapes project: ' + str(value))
    name = path.relative_to(ROOT).as_posix()
    index = ROOT / 'records/retention/manifest.json'
    if index.is_file():
        manifest = json.loads(index.read_text(encoding='utf-8'))
        row = manifest['relocations'].get(name)
        if row is None:
            row = next((r for r in manifest['relocations'].values()
                        if r['path'] == name), None)
        if row:
            retention_path = ROOT / 'records/retention/retention.json'
            if retention_path.is_file():
                policy = json.loads(retention_path.read_text(encoding='utf-8'))
                if policy.get('raw_payloads_retained') is False:
                    raise FileNotFoundError('original IQ intentionally removed by retention policy; final conclusions remain: ' + name)
            retained = (ROOT / row['path']).resolve()
            if (retained.is_relative_to(ROOT / 'records/retention') and retained.is_file()
                    and retained.stat().st_size == row['bytes']):
                return retained
            raise ValueError('retained IQ identity/length differs: ' + name)
    if path.is_file():
        return path
    location_index = ROOT / 'records/index.json'
    locations = json.loads(location_index.read_text(encoding='utf-8')) if location_index.is_file() else {}
    relocations = locations.get('relocations', {})

    def retained_file(candidate):
        retained = (ROOT / relocations.get(candidate, candidate)).resolve()
        if not retained.is_relative_to(ROOT):
            raise ValueError('recorded relocation escapes project: ' + candidate)
        return retained if retained.is_file() else None

    retained = retained_file(name)
    if retained:
        return retained
    # Metadata stored beside historical raw can itself have been archived.
    ledger = ROOT / 'records/maintenance/2026-10-28-consolidation-migration.json'
    if ledger.is_file():
        moves = json.loads(ledger.read_text(encoding='utf-8'))['moves']
        for row in sorted(moves, key=lambda r: -len(r['source'])):
            source = row['source']
            if name == source or name.startswith(source + '/'):
                retained = retained_file(row['destination'] + name[len(source):])
                if retained:
                    return retained
                break
    archive_name = locations.get('archive')
    if archive_name:
        archive = (ROOT / archive_name).resolve()
        if not archive.is_relative_to(ROOT):
            raise ValueError('recorded archive escapes project')
        if archive.is_file():
            with zipfile.ZipFile(archive) as saved:
                if name in saved.namelist():
                    raise FileNotFoundError('recorded metadata archived locally; archive: '
                                            + archive_name + '; member: ' + name)
    raise FileNotFoundError('recorded artifact not retained: ' + name)
