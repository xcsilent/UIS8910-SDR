"""Offline repository inventory and documentation checks; never access hardware.

The inventory reads file metadata, not payload contents. Git internals and directory
junctions are excluded. It does not delete files, change the index, or publish.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def capture_cleanup(output, apply=False):
    """Delete only explicitly scoped capture payloads after final tables exist.

    The user explicitly authorized removal of original IQ on2026-10-30. Never
    traverse SDKs, builds outside work, frozen archives, or directory links.
    Metadata is retained; .bin files can be live firmware and are excluded.
    """
    if not (ROOT / 'docs/data/sdr-capabilities.json').is_file():
        raise ValueError('derive the final capability tables before cleanup')
    output.mkdir(parents=True, exist_ok=True)
    plan_path = output / 'capture-cleanup.json'
    if apply and plan_path.exists():
        old = json.loads(plan_path.read_text(encoding='utf-8'))
        if old.get('applied'):
            raise ValueError('cleanup already recorded; preserve its audit instead of overwriting it')
    rows = []
    allowed = {'.raw', '.fc32', '.cs16', '.iq'}
    for scope in ('work', 'records'):
        base = (ROOT / scope).resolve()
        for directory, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = [n for n in dirs if not (Path(directory)/n).is_symlink()
                       and not getattr(os.path, 'isjunction', lambda p: False)(Path(directory)/n)]
            for name in files:
                path = Path(directory) / name
                if path.suffix.lower() not in allowed or path.is_symlink():
                    continue
                resolved = path.resolve()
                if not resolved.is_relative_to(base):
                    raise ValueError('capture escapes allowed root: ' + str(path))
                stat = path.stat()
                rows.append({'path': path.relative_to(ROOT).as_posix(), 'bytes': stat.st_size,
                             'mtime_ns': stat.st_mtime_ns})
    result = {'schema_version': 1, 'recorded_at': datetime.now(timezone.utc).isoformat(),
              'authorization': 'User2026-10-30: includes original IQ; retain final conclusions only.',
              'scope': 'Only .raw/.fc32/.cs16/.iq in work/ and records/. No archive, SDK, toolchain, PAC, ELF or .bin deletion.',
              'payload_read_or_hashed': False, 'device_accessed': False,
              'applied': apply, 'files': rows, 'planned_files': len(rows),
              'planned_bytes': sum(r['bytes'] for r in rows), 'removed_files': 0,
              'removed_bytes': 0, 'errors': []}
    # Write the complete resolved plan before the first unlink.
    plan_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if apply:
        for row in rows:
            path = ROOT / row['path']
            try:
                stat = path.stat()
                if stat.st_size != row['bytes'] or stat.st_mtime_ns != row['mtime_ns']:
                    raise ValueError('file changed since plan was written')
                path.unlink()
                result['removed_files'] += 1
                result['removed_bytes'] += row['bytes']
            except (OSError, ValueError) as error:
                result['errors'].append({'path': row['path'], 'error': str(error)})
        plan_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, ensure_ascii=False, indent=2))
    return int(bool(result['errors']))


def export_source(destination, refresh=False):
    """Create a local, review-only source package; no Git/network operations."""
    dest = destination.resolve()
    previous_files = set()
    if not dest.is_relative_to(ROOT / 'work') or dest == ROOT / 'work':
        raise ValueError('choose a new review directory strictly inside work/')
    if dest.exists() and not (refresh and (dest/'EXPORT-REVIEW.json').is_file()):
        raise ValueError('destination exists; --refresh requires an existing managed EXPORT-REVIEW.json')
    if refresh and (dest/'EXPORT-REVIEW.json').is_file():
        previous = json.loads((dest/'EXPORT-REVIEW.json').read_text(encoding='utf-8'))
        previous_files = {row['path'] for row in previous['files']}
    policy = json.loads((ROOT / 'docs/publication-manifest.json').read_text(encoding='utf-8'))
    selected = set()
    allowed = set(policy['allowed_suffixes'])
    for prefix in policy['source_directories']:
        for path in (ROOT / prefix).rglob('*'):
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in allowed and '__pycache__' not in path.parts:
                selected.add(path.relative_to(ROOT).as_posix())
    for name in policy['individual_files']:
        if not (ROOT/name).is_file():
            raise ValueError('missing publication source: ' + name)
        selected.add(name)
    caps = json.loads((ROOT/'docs/data/sdr-capabilities.json').read_text(encoding='utf-8'))
    selected.update(caps['sources'].values())
    selected.update(r['record'] for r in caps['communication_10s'])
    for prefix in policy['excluded_prefixes']:
        selected = {name for name in selected if not name.startswith(prefix)}
    # Include only small, directly cited final metadata, not the transitive JSON
    # experiment graph. JSON strings may identify excluded historical inputs.
    if policy.get('include_linked_record_summaries'):
        pending = [name for name in selected if name.endswith('.md')]
        inspected = set()
        while pending:
            name = pending.pop()
            if name in inspected:
                continue
            inspected.add(name)
            path = ROOT/name
            for target in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8-sig')):
                target = target.strip('<>').split('#', 1)[0]
                if not target or '://' in target or target.startswith('mailto:'):
                    continue
                resolved = (path.parent/unquote(target)).resolve()
                if (resolved.is_relative_to(ROOT/'records') and resolved.is_file()
                        and resolved.suffix in ('.json', '.md', '.txt', '.csv')
                        and resolved.stat().st_size <= 2*1024*1024):
                    relative = resolved.relative_to(ROOT).as_posix()
                    if relative not in selected:
                        selected.add(relative)
                        if resolved.suffix == '.md':
                            pending.append(relative)
    dest.mkdir(parents=True, exist_ok=refresh)
    removed_export_copies = []
    for name in sorted(previous_files - selected):
        stale = (dest/name).resolve()
        if not stale.is_relative_to(dest):
            raise ValueError('previous export entry escapes review directory: ' + name)
        if stale.is_file():
            stale.unlink()
            removed_export_copies.append(name)
    copied = []
    for name in sorted(selected):
        source = ROOT / name
        if not source.resolve().is_relative_to(ROOT) or source.is_symlink():
            raise ValueError('unsafe publication source: ' + name)
        target = dest/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append({'path': name, 'bytes': source.stat().st_size})
    external = []
    rewritten_documents = []
    for row in copied:
        path = dest/row['path']
        if path.suffix != '.md':
            continue
        body = path.read_text(encoding='utf-8-sig')
        def rewrite_local_reference(match):
            target = match.group(2).strip('<>').split('#', 1)[0]
            if not target or '://' in target or target.startswith('mailto:'):
                return match.group(0)
            resolved = (path.parent / unquote(target)).resolve()
            if not resolved.is_relative_to(dest) or not resolved.exists():
                external.append({'document': row['path'], 'local_only_reference': target})
                return match.group(1) + ' (local-only research reference, omitted: `' + target + '`)'
            return match.group(0)
        rewritten = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', rewrite_local_reference, body)
        if rewritten != body:
            path.write_text(rewritten, encoding='utf-8', newline='\n')
            rewritten_documents.append(row['path'])
        row['bytes'] = path.stat().st_size
    report = {'status': 'local_review_only_not_publication_ready', 'files': copied,
              'total_bytes': sum(r['bytes'] for r in copied), 'device_accessed': False,
              'uploaded': False, 'license_granted': False, 'external_local_references': external,
              'export_only_reference_rewrites': rewritten_documents,
              'removed_superseded_export_copies': removed_export_copies,
              'known_external_dependencies': policy['external_dependencies'],
              'note': 'License/provenance and privacy review required. Omitted local references are labeled as unavailable in exported Markdown; original workspace documents are unchanged.'}
    (dest/'EXPORT-REVIEW.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'directory': dest.relative_to(ROOT).as_posix(),
                      'files': len(copied), 'bytes': report['total_bytes'], 'external_local_references': len(external)}))
    return 0


def inventory(output):
    output.mkdir(parents=True, exist_ok=True)
    totals = defaultdict(lambda: {'files': 0, 'bytes': 0})
    extensions = Counter()
    largest = []
    skipped = []
    errors = []
    licenses = []
    dest = output / 'file-inventory.jsonl.gz'
    with gzip.open(dest, 'wt', encoding='utf-8', newline='\n') as stream:
        def walk_error(error):
            errors.append({'path': str(error.filename), 'error': type(error).__name__})

        for directory, dirs, files in os.walk(ROOT, followlinks=False, onerror=walk_error):
            keep = []
            for name in sorted(dirs):
                path = Path(directory) / name
                if name == '.git':
                    continue
                if path.is_symlink() or getattr(os.path, 'isjunction', lambda p: False)(path):
                    skipped.append(path.relative_to(ROOT).as_posix())
                else:
                    keep.append(name)
            dirs[:] = keep
            for name in sorted(files):
                path = Path(directory) / name
                if path == dest or path.is_symlink():
                    continue
                rel = path.relative_to(ROOT).as_posix()
                try:
                    stat = path.lstat()
                except OSError as error:
                    errors.append({'path': rel, 'error': type(error).__name__})
                    continue
                parts = Path(rel).parts
                group = '/'.join(parts[:2]) if len(parts) > 2 else parts[0]
                for key in {'ALL', parts[0], group}:
                    totals[key]['files'] += 1
                    totals[key]['bytes'] += stat.st_size
                extensions[path.suffix.lower() or '(none)'] += 1
                row = {'path': rel, 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
                       'reparse_point': bool(getattr(stat, 'st_file_attributes', 0) & 0x400)}
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                largest.append({'path': rel, 'bytes': stat.st_size})
                if len(largest) > 200:
                    largest = sorted(largest, key=lambda x: x['bytes'], reverse=True)[:100]
                if name.lower().startswith(('license', 'copying', 'notice', 'copyright')):
                    licenses.append(rel)
    result = {
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'All local file metadata except .git internals, symlinks/junctions and the inventory itself. No payload hashes or raw data reads.',
        'device_accessed': False,
        'groups': dict(sorted(totals.items())),
        'extensions': dict(extensions.most_common()),
        'largest_files': sorted(largest, key=lambda x: x['bytes'], reverse=True)[:100],
        'license_notice_paths': sorted(licenses),
        'skipped_links': skipped,
        'errors': errors,
    }
    (output / 'inventory-summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    status = subprocess.run(['git', 'status', '--porcelain=v1', '-z', '--untracked-files=all'], cwd=ROOT, capture_output=True, check=True)
    (output / 'git-status.z').write_bytes(status.stdout)
    print(json.dumps({'files': totals['ALL']['files'], 'bytes': totals['ALL']['bytes'], 'errors': len(errors), 'inventory': dest.relative_to(ROOT).as_posix()}))


def check_docs():
    state = json.loads((ROOT / 'docs/project-state.json').read_text(encoding='utf-8-sig'))
    files = set(state['active_documents'])
    files.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'docs').rglob('*.md'))
    files.update(p.relative_to(ROOT).as_posix() for p in ROOT.glob('*.md'))
    files.update(p.relative_to(ROOT).as_posix() for p in (ROOT / '.github').rglob('*.md'))
    files.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'records').rglob('*.md'))
    broken = []
    count = 0
    for relative in sorted(files):
        path = ROOT / relative
        text = path.read_text(encoding='utf-8-sig')
        for target in re.findall(r'\]\(([^)]+)\)', text):
            target = target.strip('<>').split('#', 1)[0]
            if not target or '://' in target or target.startswith('mailto:'):
                continue
            resolved = (path.parent / unquote(target)).resolve()
            count += 1
            if not resolved.is_relative_to(ROOT) or not resolved.exists():
                broken.append({'file': relative, 'target': target})
    return {'status': 'passed' if not broken else 'failed', 'device_accessed': False,
            'documents': len(files), 'local_links': count, 'broken_links': broken}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['inventory', 'docs', 'captures', 'export'])
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'records/maintenance')
    parser.add_argument('--apply', action='store_true', help='captures only: remove explicitly authorized IQ intermediates')
    parser.add_argument('--destination', type=Path, help='export only: new review directory under work/')
    parser.add_argument('--refresh', action='store_true', help='export only: update a previously generated local review copy')
    args = parser.parse_args()
    if args.command == 'captures':
        output = args.output_dir.resolve()
        if not output.is_relative_to(ROOT/'records'):
            parser.error('capture audit must be inside records/')
        return capture_cleanup(output, args.apply)
    if args.command == 'export':
        if args.destination is None:
            parser.error('export requires --destination')
        return export_source(args.destination, args.refresh)
    if args.apply:
        parser.error('--apply is only valid for captures')
    if args.command == 'inventory':
        output = args.output_dir.resolve()
        if not output.is_relative_to(ROOT):
            parser.error('output must be inside the repository')
        inventory(output)
        return 0
    result = check_docs()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
