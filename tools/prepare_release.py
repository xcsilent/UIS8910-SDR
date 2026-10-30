"""Prepare local UIS8910-SDR source/binary publication copies; never upload.

SPDX-License-Identifier: GPL-3.0-or-later
No hardware, Git or network calls. Research records and deployed artifacts are
read-only inputs. --refresh affects only this tool's managed work directory.
"""
import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import zipfile

from repository_audit import export_source

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {'.c', '.h', '.cpp', '.hpp', '.s', '.inc', '.ld', '.py', '.json',
                 '.md', '.txt', '.yml', '.yaml', '.svg', '.csv'}
PRIVATE_KEYS = re.compile(r'^(?:(?:b210|usrp|device|reference|usb)_)?serial(?:_number)?$|'
                          r'^(?:(?:pnp|device)_)?instance_?id$', re.I)
FORBIDDEN = {'.raw', '.iq', '.fc32', '.cs16', '.log', '.pdb', '.pcap', '.pcapng'}
HOLDS = [
    {'component': 'vendor PAC and SDK objects',
     'scope': 'Source build inputs and firmware ZIP',
     'remaining': 'Establish redistribution terms for modem/RF/boot/NV and vendor objects; SDK root GPL text is insufficient.'},
    {'component': 'ARM GCC 7.2.1 / binutils bundle',
     'scope': 'Source build inputs',
     'remaining': 'Recover original distribution notices, provenance and applicable corresponding source before public upload.'},
]


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_file(path):
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in {
        'LICENSE', 'COPYING', 'VERSION', '.gitignore', '.rgignore', 'copyright'}


class Redactor:
    def __init__(self, paths):
        self.ids = set()
        self.counts = Counter()
        self.home = os.environ.get('USERPROFILE', str(Path.home()))
        self.roots = [str(ROOT), ROOT.as_posix(),
                      '/mnt/'+ROOT.drive[:1].lower()+ROOT.as_posix()[2:]]
        # Discover identifiers from copied records, not a hard-coded local device.
        for path in paths:
            if path.suffix == '.json':
                self.collect(load(path))
            if text_file(path):
                body = path.read_text(encoding='utf-8-sig')
                for value in re.findall(r'(?:--serial[ =]+|serial=|Serial:\s*)([A-Za-z0-9_-]{6,})', body, re.I):
                    if (any(c.isdigit() for c in value)
                            and value.upper() not in {'B210_SERIAL', 'DEVICE_SERIAL', 'REFERENCE_SERIAL'}):
                        self.ids.add(value)
        self.ids = {s for s in self.ids if len(s) >= 6}

    def collect(self, obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if PRIVATE_KEYS.fullmatch(key) and isinstance(value, (str, int)):
                    self.ids.add(str(value))
                    # Windows PnP instances can embed the B210 serial in logs.
                    if isinstance(value, str) and '\\' in value:
                        self.ids.add(value.rsplit('\\', 1)[-1])
                self.collect(value)
        elif isinstance(obj, list):
            for item in obj:
                self.collect(item)

    def string(self, value, count=True):
        def sub(pattern, replacement, category, flags=0):
            nonlocal value
            value, n = re.subn(pattern, lambda _: replacement, value, flags=flags)
            if count:
                self.counts[category] += n
        # Escape variants occur inside command/log strings and generated code.
        for root in sorted(set(self.roots), key=len, reverse=True):
            for form in (root.replace('\\', '\\\\'), root):
                sub(re.escape(form), 'C:/Projects/UIS8910-SDR', 'workspace_path', re.I)
        sub(r'[A-Z]:[\\/]+Users[\\/]+[^\\/\s\x00"\'<>]+',
            'C:/home/USER', 'home_path', re.I)
        sub(r'/(?:home|Users)/[^/\s\x00"\'<>]+', '/home/USER', 'home_path')
        for identifier in sorted(self.ids, key=len, reverse=True):
            sub(re.escape(identifier), 'DEVICE_ID_REDACTED', 'device_identifier')
        return value

    def object(self, obj):
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                if PRIVATE_KEYS.fullmatch(key) and isinstance(value, (str, int)):
                    self.counts['device_identifier_field'] += 1
                    result[self.string(key)] = 'DEVICE_ID_REDACTED'
                else:
                    result[self.string(key)] = self.object(value)
            return result
        if isinstance(obj, list):
            return [self.object(item) for item in obj]
        return self.string(obj) if isinstance(obj, str) else obj

    def sanitize(self, path):
        before = path.read_bytes()
        if path.suffix == '.json':
            obj = load(path)
            # Keep cleanup conclusions, not local filename inventories.
            if path.name in {'capture-cleanup.json', 'capture-log-cleanup.json', 'inventory-summary.json'}:
                inventory_keys = {'files', 'largest_files', 'license_notice_paths', 'skipped_links',
                                  'removed', 'removed_paths', 'removed_payloads', 'groups', 'extensions'}
                obj = {k:v for k,v in obj.items() if k not in inventory_keys}
                obj['publication_note'] = 'Local filename inventories omitted; final cleanup totals retained.'
            save(path, self.object(obj))
        elif text_file(path):
            path.write_text(self.string(path.read_text(encoding='utf-8-sig')), encoding='utf-8', newline='\n')
        return before != path.read_bytes()

    def scan(self, base):
        findings = []
        counts = Counter()
        home_markers = [self.home, self.home.replace('\\', '/'), self.home.replace('\\', '\\\\')]
        markers = list(self.ids) + home_markers + self.roots
        markers = {s for s in markers if len(s) >= 6}
        credentials = re.compile(rb'(?:gh[pousr]_[A-Za-z0-9_]{25,}|github_pat_[A-Za-z0-9_]{30,}|'
                                 rb'AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
        private_parts = {'.git', '__pycache__', '.aws', '.codex', '.ssh', '.codebuddy'}

        def check_data(label, data, category='known_personal_marker'):
            hits = 0
            folded = data.lower()
            for marker in markers:
                for encoding in ('utf-8', 'utf-16-le'):
                    if marker.encode(encoding).lower() in folded:
                        hits += 1
                        break
            if hits:
                findings.append({'path': self.string(label, count=False), 'category': category, 'count': hits})
            if credentials.search(data):
                findings.append({'path': self.string(label, count=False), 'category': 'credential_pattern'})

        def inspect(label, data, depth=0):
            counts['payloads_scanned'] += 1
            check_data(label, label.encode('utf-8'), 'personal_marker_in_filename')
            parts = Path(label.replace('!/', '/').replace('\\', '/')).parts
            if Path(label).suffix.lower() in FORBIDDEN or private_parts.intersection(parts):
                findings.append({'path': self.string(label, count=False), 'category': 'excluded_payload_or_private_directory'})
            if label.lower().endswith('.zip') and depth < 3:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    for info in archive.infolist():
                        if not info.is_dir():
                            inspect(label+'!/'+info.filename, archive.read(info), depth+1)
                return
            check_data(label, data)

        for path in sorted(base.rglob('*')):
            if not path.is_file():
                continue
            label = path.relative_to(base).as_posix()
            inspect(label, path.read_bytes())
        return {'status': 'passed' if not findings else 'failed',
                'scope': 'Known device IDs and paths in filenames and ASCII/UTF-16 content, credential patterns and forbidden payload/private directories; nested ZIP members included. Upstream author/license credits preserved; arbitrary binary NV fields not decoded.',
                **counts, 'findings': findings}


def copy_verified(source, target, expected=None):
    if not source.is_file() or source.is_symlink():
        raise ValueError('missing/unsafe release input: '+source.relative_to(ROOT).as_posix())
    if expected and digest(source) != expected:
        raise ValueError('manifest identity differs: '+source.relative_to(ROOT).as_posix())
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def scrub_diagnostic_path(path):
    """Replace only local UTF-16 source-path prefixes in PE .rdata, in a copy.

    Keep file size, section/header layout and all executable sections identical.
    A signed image or a match outside read-only initialized data is rejected.
    """
    before = path.read_bytes()
    pe = struct.unpack_from('<I', before, 0x3c)[0]
    if before[:2] != b'MZ' or before[pe:pe+4] != b'PE\0\0':
        raise ValueError('not a PE image')
    count = struct.unpack_from('<H', before, pe+6)[0]
    optional_size = struct.unpack_from('<H', before, pe+20)[0]
    optional = pe+24
    if struct.unpack_from('<H', before, optional)[0] != 0x20b:
        raise ValueError('only PE32+ diagnostic paths supported')
    if any(struct.unpack_from('<II', before, optional+112+8*4)):
        raise ValueError('do not rewrite signed PE images')
    sections = []
    for index in range(count):
        at = optional+optional_size+40*index
        name = before[at:at+8].rstrip(b'\0').decode('ascii')
        size, offset = struct.unpack_from('<II', before, at+16)
        flags = struct.unpack_from('<I', before, at+36)[0]
        sections.append((name, offset, size, flags))
    after = bytearray(before)
    patches = []
    root = str(ROOT)
    replacement = 'C:\\src\\UIS8910-SDR'
    if len(replacement) > len(root):
        replacement = 'C:\\src'
    replacement += '\\'*(len(root)-len(replacement))
    needle, public = root.encode('utf-16-le'), replacement.encode('utf-16-le')
    begin = 0
    while True:
        at = before.lower().find(needle.lower(), begin)
        if at < 0:
            break
        matches = [s for s in sections if s[1] <= at and at+len(needle) <= s[1]+s[2]]
        if (len(matches) != 1 or matches[0][0] != '.rdata'
                or matches[0][3] & (0x20000000 | 0x80000000)):
            raise ValueError('local path match is outside read-only PE data')
        after[at:at+len(needle)] = public
        patches.append({'offset': at, 'bytes': len(needle), 'section': '.rdata',
                        'purpose': 'diagnostic source path prefix only'})
        begin = at+len(needle)
    executable = []
    for name, at, size, flags in sections:
        if flags & 0x20000000:
            assert before[at:at+size] == after[at:at+size]
            executable.append({'section': name, 'sha256': hashlib.sha256(before[at:at+size]).hexdigest()})
    assert len(before) == len(after)
    if patches:
        path.write_bytes(after)
    return {'modified': bool(patches), 'original_sha256': hashlib.sha256(before).hexdigest(),
            'publication_sha256': digest(path), 'patches': patches,
            'executable_sections_unchanged': executable, 'length_unchanged': True,
            'original_input_modified': False}


def check_sdrpp_copy(plugin, runtime, expected_core):
    if os.name != 'nt' or not (runtime/'sdrpp_core.dll').is_file():
        return {'status': 'not_run', 'reason': 'matching Windows SDR++ runtime unavailable', 'device_accessed': False}
    if digest(runtime/'sdrpp_core.dll') != expected_core:
        raise ValueError('SDR++ offline load check requires the exact target core')
    code = ('import ctypes,json,os,sys;'
            'dirs=[os.add_dll_directory(sys.argv[1]),os.add_dll_directory(sys.argv[2])];'
            'm=ctypes.WinDLL(sys.argv[3]);'
            '[getattr(m,n) for n in ("_INIT_","_CREATE_INSTANCE_","_DELETE_INSTANCE_","_END_")];'
            'print(json.dumps(dict(status="passed",device_accessed=False,plugin_loaded=True,entry_points_resolved=True,instance_created=False)))')
    result = subprocess.run([sys.executable, '-B', '-c', code, str(plugin.parent), str(runtime), str(plugin)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError('SDR++ publication DLL load failed (exit '+str(result.returncode)+')')
    report = json.loads(result.stdout)
    harness = ROOT/'work/sdrpp/checks/fft-test.exe'
    if harness.is_file():
        env = dict(os.environ, PATH=str(runtime)+os.pathsep+os.environ.get('PATH', ''))
        fft = subprocess.run([str(harness)], cwd=harness.parent, env=env,
                             capture_output=True, text=True, timeout=30)
        if fft.returncode:
            raise ValueError('real-core FFT offline regression failed')
        report['real_core_fft'] = json.loads(fft.stdout)
    return report


def write_zip(directory, output):
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(directory.rglob('*')):
            if path.is_file():
                info = zipfile.ZipInfo(path.relative_to(directory).as_posix(), (2026, 10, 30, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())


def notes(path, component, instructions):
    path.write_text('# UIS8910-SDR v0.1 — '+component+'\n\n'+instructions+
                    '\n\nRX only. BW0/BW1 fit the raw USB budget; wider modes can have gaps.\n'
                    'RF envelopes are discrete/conditional measurements, not guaranteed continuous coverage.\n'
                    'Original project contributions: GPL-3.0-or-later. Third-party terms remain applicable.\n'
                    'See LICENSE, THIRD_PARTY_NOTICES.md and manifest.json. No IQ or personal configuration is included.\n',
                    encoding='utf-8', newline='\n')


def nv_provenance(pac):
    sys.path.insert(0, str(ROOT/'tools/usb'))
    from pac import entries
    nv = next(row['data'] for name,row in entries(pac.read_bytes()).items() if name.endswith('_nvitem.bin'))
    sdk = ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/nvm/nvitem.bin'
    result = {'pac_nv_bytes': len(nv), 'pac_nv_sha256': hashlib.sha256(nv).hexdigest(),
              'scope': 'Template provenance comparison; NV fields and redistribution terms are not fully decoded.'}
    if sdk.is_file():
        data = sdk.read_bytes()
        result.update(sdk_template_bytes=len(data), sdk_template_sha256=digest(sdk),
                      differing_template_offsets=[i for i,(a,b) in enumerate(zip(nv,data)) if a!=b],
                      payload_after_first_two_bytes_matches=nv[2:len(data)]==data[2:],
                      trailing_bytes=len(nv)-len(data), trailing_is_ff=all(b==255 for b in nv[len(data):]))
    else:
        result['local_sdk_template_comparison'] = 'not available on this machine'
    return result


def run_check(source, script, *args):
    p = subprocess.run([sys.executable, '-B', str(source/'tools'/script), *args], cwd=source,
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90)
    try:
        output = json.loads(p.stdout)
    except ValueError:
        output = {'stdout': p.stdout[-2000:], 'stderr': p.stderr[-2000:]}
    if p.returncode:
        raise ValueError(script+' failed: '+json.dumps(output, ensure_ascii=True))
    return {'command': 'python -B tools/'+script+' '+' '.join(args), 'exit_code': p.returncode, 'result': output}


def prepare(destination, refresh=False, sdrpp_root=Path('D:/Tools/sdrpp_windows_x64')):
    dest = destination.resolve()
    if not dest.is_relative_to((ROOT/'work').resolve()) or dest == (ROOT/'work').resolve():
        raise ValueError('choose a directory strictly inside work/')
    marker = dest/'preparation-report.json'
    if dest.exists():
        if not refresh or not marker.is_file() or load(marker).get('managed_by') != 'tools/prepare_release.py':
            raise ValueError('existing destination requires --refresh and this tool\'s management report')
        # Resolve and check all targets before deleting only generated copies.
        for directory, dirs, files in os.walk(dest, followlinks=False):
            for name in dirs+files:
                path = Path(directory)/name
                if (path.is_symlink() or getattr(os.path, 'isjunction', lambda p: False)(path)
                        or not path.resolve().is_relative_to(dest)):
                    raise ValueError('managed publication copy contains a link/escaping target')
        for name in ('source', 'release'):
            target = (dest/name).resolve()
            if not target.is_relative_to(dest):
                raise ValueError('unsafe generated copy target')
            if target.exists():
                shutil.rmtree(target)
    dest.mkdir(parents=True, exist_ok=True)
    save(marker, {'managed_by': 'tools/prepare_release.py', 'status': 'preparing', 'uploaded': False})
    source = dest/'source'
    release = dest/'release'
    release.mkdir()
    export_source(source)
    (source/'EXPORT-REVIEW.json').unlink()

    snapshot = ROOT/'outputs/firmware/v0.1/source-snapshot'
    snapshot_files = [p for p in snapshot.rglob('*') if p.is_file()]
    differences = []
    for path in snapshot_files:
        name = path.relative_to(snapshot)
        copy_verified(path, source/'firmware-source-v0.1'/name)
        if (ROOT/name).is_file() and path.read_bytes() != (ROOT/name).read_bytes():
            differences.append(name.as_posix())
    (source/'firmware-source-v0.1/README.md').write_text(
        '# Retained firmware v0.1 project source\n\n'
        'This is the retained project-source snapshot for the tested PAC, not another firmware release.\n'
        'It excludes vendor binaries and IQ. Active source and the relocatable build are at repository root.\n'
        'Changed active files: '+', '.join(differences)+'.\n'
        'New active-source builds are unflashed candidates; exact old binary reproduction is not claimed.\n', encoding='utf-8')

    firmware = load(ROOT/'outputs/firmware/current/manifest.json')
    host = load(ROOT/'outputs/host/manifest.json')
    groups = {'firmware': [], 'windows': [], 'soapy': [], 'sdrpp': []}
    for row in firmware['artifacts']:
        copy_verified(ROOT/row['path'], release/'firmware'/Path(row['path']).name, row['sha256'])
        groups['firmware'].append({'path': Path(row['path']).name, 'sha256': row['sha256']})
    for row in host['artifacts']:
        part = Path(row['path']).parts[2]
        group = 'windows' if part in ('windows', 'tune') else part
        relative = Path(*Path(row['path']).parts[2:])
        copy_verified(ROOT/row['path'], release/group/'outputs/host'/relative, row['sha256'])
        groups[group].append({'path': ('outputs/host'/relative).as_posix(), 'sha256': row['sha256']})
    # Keep minimal build/ABI metadata where the installer expects it.
    for component in ('windows', 'soapy', 'sdrpp'):
        group = component
        copy_verified(ROOT/'outputs/host'/component/'build.json', release/group/'outputs/host'/component/'build.json')
    published_plugin = release/'sdrpp/outputs/host/sdrpp/uis8910_source.dll'
    plugin_adjustment = scrub_diagnostic_path(published_plugin)
    for row in groups['sdrpp']:
        if row['path'].endswith('/uis8910_source.dll'):
            row['sha256'] = digest(published_plugin)
    plugin_build_path = release/'sdrpp/outputs/host/sdrpp/build.json'
    plugin_build = load(plugin_build_path)
    for row in plugin_build['artifacts']:
        if row['path'].endswith('/uis8910_source.dll'):
            row['sha256'] = digest(published_plugin)
    plugin_build['publication_diagnostic_path_adjustment'] = plugin_adjustment
    save(plugin_build_path, plugin_build)
    for group in groups:
        folder = release/group
        for name in ('LICENSE', 'LICENSE-STATUS.md', 'THIRD_PARTY_NOTICES.md'):
            copy_verified(ROOT/name, folder/name)
        # These ZIPs are usable independently; point absent source documents to
        # the companion source archive instead of leaving broken relative links.
        license_scope = folder/'LICENSE-STATUS.md'
        license_scope.write_text(license_scope.read_text(encoding='utf-8').replace(
            '[the publication procedure](docs/publishing.md)',
            '`docs/publishing.md` in the companion UIS8910-SDR-v0.1-source.zip'), encoding='utf-8')
        notices_path = folder/'THIRD_PARTY_NOTICES.md'
        notices_path.write_text(notices_path.read_text(encoding='utf-8').replace(
            '[host manifest](outputs/host/manifest.json)',
            '`outputs/host/manifest.json` in the companion UIS8910-SDR-v0.1-source.zip'
            ' (this package\'s artifact hashes are in manifest.json)'), encoding='utf-8')
        save(folder/'manifest.json', {'release': '0.1.0', 'component': group, 'artifacts': groups[group],
                                      'source_package': 'UIS8910-SDR-v0.1-source.zip',
                                      'paired_components_must_stay_together': True,
                                      'binary_modified': group == 'sdrpp' and plugin_adjustment['modified'],
                                      'new_hardware_test': False})
    copy_verified(ROOT/'outputs/host/soapy/SoapySDR-LICENSE.txt', release/'soapy/SoapySDR-LICENSE.txt')
    copy_verified(ROOT/'outputs/host/sdrpp/COPYING', release/'sdrpp/COPYING')
    for package in ('mingw-w64-common', 'mingw-w64-x86-64-dev', 'gcc-mingw-w64-base'):
        copy_verified(ROOT/'work/windows-toolchain/root/usr/share/doc'/package/'copyright',
                      release/'soapy/notices'/(package+'-copyright.txt'))
    target_core = load(ROOT/'outputs/host/sdrpp/build.json')['target_sdrpp_core_sha256']
    notes(release/'firmware/README.md', 'firmware',
          'For Air724UG / UIS8910DM only. Flash manually with the compatible vendor PAC tool.\n'
          'PAC SHA256: '+firmware['artifacts'][0]['sha256']+'\n'
          'CP generation: 0x526f0501. Retains vendor boot/RF/calibration dependencies.\n'
          'Vendor redistribution terms remain unresolved; this is a local preparation package.\n'
          'Other module/board variants are untested. Flashing is not performed by this package.')
    notes(release/'windows/README.md', 'Windows x64 receive tools',
          'Keep windows/ and tune/ DLLs paired separately. Only one consumer may own the device.\n'
          'Install/bind WinUSB to the raw streaming interface while retaining the debug COM interface;\n'
          'see the source package docs/getting-started.md. COM9 is only an example.\n\n'
          '```powershell\n.\\outputs\\host\\windows\\sdr_receive.exe --port COM9 --frequency-hz 2300000000 '
          '--gain-index 30 --bandwidth-index 0 --milliseconds 10000 --output receive.raw\n```\n'
          'This command creates a NEW raw IQ file. No historical IQ is distributed.\n'
          'Default raw: signed12 in bits15:4 of two LE int16 lanes, 4 B/complex sample.')
    notes(release/'soapy/README.md', 'Windows x64 SoapySDR 0.8.1',
          'Keep all outputs/host/soapy DLLs together; do not replace sdr_usb.dll with another component\'s copy.\n\n'
          '```powershell\n$env:PATH="$PWD\\outputs\\host\\soapy;$env:PATH"\n'
          '$env:SOAPY_SDR_PLUGIN_PATH="$PWD\\outputs\\host\\soapy"\n'
          '.\\outputs\\host\\soapy\\SoapySDRUtil.exe "--probe=driver=uis8910,port=COM9"\n```\n'
          'COM9 is an example; release other consumers. Antenna=Auto selects internal routing.\n'
          'See source docs/getting-started.md for sample-rate, BW4/BW5 and stream-gap semantics.')
    notes(release/'sdrpp/README.md', 'Windows x64 SDR++ native plugin',
          'Close SDR++ before installing. Copy outputs/host/sdrpp/uis8910_source.dll into modules/;\n'
          'copy its paired sdr_usb.dll into the portable SDR++ root. Do not mix DLL versions.\n'
          'Target SDR++ source: f10fb98af8b80de01de94e60c17608e4281e2515.\n'
          'Target sdrpp_core.dll SHA256: '+target_core+'.\n'
          'A matching version label alone does not establish C++ ABI compatibility.\n'
          'Publication copy replaces an embedded local UTF-16 diagnostic path prefix in .rdata.\n'
          'Executable sections and paired receive DLL are unchanged; see build.json for before/after hashes.\n'
          'Start SDR++, choose Source UIS8910, select the actual COM port and set frequency.\n'
          'Auto routing hides internal LTE-band choices. SDR++ itself is not bundled.')

    paths = [p for p in source.rglob('*') if p.is_file()]
    paths += [p for p in release.rglob('*') if p.is_file() and text_file(p)]
    redactor = Redactor(paths)
    changed = []
    for path in paths:
        if text_file(path) and redactor.sanitize(path):
            changed.append(path.relative_to(dest).as_posix())
    save(source/'SOURCE-PACKAGE.json', {'project': 'UIS8910-SDR', 'version': '0.1.0',
         'original_license': 'GPL-3.0-or-later', 'uploaded': False, 'git_history_included': False,
         'iq_payloads_included': False, 'personal_identifiers_redacted': True,
         'third_party_distribution_items': HOLDS,
         'firmware_snapshot_files': len(snapshot_files), 'active_source_differs_from_snapshot': differences,
         'measurement_scope': 'Final numerical summaries; original IQ intentionally removed, no spectral replay available.'})
    checks = [run_check(source, 'check_publication.py'), run_check(source, 'prepare_build.py', '--check'),
              run_check(source, 'usb/prepare_soapy_sdk.py', '--check-source')]
    plugin_check = check_sdrpp_copy(published_plugin, sdrpp_root.resolve(), target_core)
    # Do not emit absolute personal paths returned by build-input checkers.
    checks = redactor.object(checks)
    scan = redactor.scan(dest)
    if scan['status'] != 'passed':
        save(marker, {'managed_by': 'tools/prepare_release.py', 'status': 'privacy_scan_failed', 'scan': scan, 'uploaded': False})
        raise ValueError('publication scan failed; see preparation-report.json (findings contain no secret values)')
    pac = ROOT/firmware['artifacts'][0]['path']
    archive_paths = []
    for group in groups:
        path = release/('UIS8910-SDR-v0.1-'+group+'.zip')
        write_zip(release/group, path)
        archive_paths.append(path)
    path = release/'UIS8910-SDR-v0.1-source.zip'
    write_zip(source, path)
    archive_paths.append(path)
    assets = [{'path': p.relative_to(dest).as_posix(), 'bytes': p.stat().st_size, 'sha256': digest(p)} for p in archive_paths]
    (release/'SHA256SUMS.txt').write_text(''.join(row['sha256']+'  '+Path(row['path']).name+'\n' for row in assets), encoding='ascii')
    report = {'managed_by': 'tools/prepare_release.py', 'status': 'prepared_locally_distribution_questions_open',
              'project': 'UIS8910-SDR', 'release': '0.1.0', 'original_contributions_license': 'GPL-3.0-or-later',
              'uploaded': False, 'git_history_included': False, 'device_accessed': False,
              'local_original_evidence_modified': False, 'source_files': sum(p.is_file() for p in source.rglob('*')),
              'assets': assets, 'redacted_or_normalized_copies': changed, 'redactions': dict(redactor.counts),
              'privacy_scan': scan, 'portable_checks': checks, 'nv_template_provenance': nv_provenance(pac),
              'sdrpp_publication_binary_adjustment': plugin_adjustment, 'sdrpp_offline_check': plugin_check,
              'remaining_distribution_items': HOLDS,
              'source_binary_correspondence': {
                  'firmware_snapshot_files': len(snapshot_files), 'active_firmware_source_differences': differences,
                  'host_pairings': 'Current host manifest pairings preserved. SDR++ plugin diagnostic path only sanitized in a copy; before/after hashes recorded. Other binaries unchanged.',
                  'limits': 'Current host source/build helpers are not an assertion of byte-identical old builds. Establish complete corresponding source for third-party compiler/vendor components before distribution.'}}
    save(marker, report)
    (dest/'RELEASE-NOTES.md').write_text(
        '# UIS8910-SDR v0.1 — local publication candidate\n\n'
        'Source, firmware, Windows CLI/library, Soapy and native SDR++ packages are under release/.\n'
        'Each ZIP contains usage/license/identity notes. SHA256SUMS.txt covers the ZIP assets.\n'
        'Original contributions: GPL-3.0-or-later. No IQ, personal configuration or Git history.\n'
        'No upload or new hardware test was performed.\n\n'
        'RF investigation envelopes: 687.5–1000 MHz and 1375–2786 MHz, discrete/conditional,\n'
        'not guaranteed continuous intervals. Nominal Fs 1.92–30.72 Msps, BW0–BW5.\n'
        'Native signed12 in LE16+16; ~30–32 MB/s measured USB supply, wideband gaps.\n'
        'See source/docs/performance.md and both technical reports for conditions and unknowns.\n\n'
        'Before public upload, resolve vendor PAC/SDK redistribution and ARM compiler\n'
        'notice/corresponding-source availability. These inputs are locally packaged, not declared cleared.\n'
        'The source contains the retained project firmware snapshot and current development source.\n'
        'The SDR++ publication plugin has only its embedded local diagnostic path sanitized.\n'
        'Its executable sections and paired receive DLL are unchanged; package metadata records\n'
        'both plugin hashes. Offline DLL loading passed when the matching runtime was available;\n'
        'this is not a new RF or full plugin hardware acceptance test. Deployed manifests retain\n'
        'their original identities; use each package manifest for publication-copy hashes.\n'
        'Keep DLL sets paired. Choose a fresh repository from source/, never upload the research history.\n',
        encoding='utf-8', newline='\n')
    # Inspect the actual deliverables, including the generated ZIPs, checksums,
    # notes and report. The final report update contains only scoped scan counts.
    scan = redactor.scan(dest)
    report['privacy_scan'] = scan
    report['final_deliverables_scanned'] = True
    if scan['status'] != 'passed':
        report['status'] = 'privacy_scan_failed'
        save(marker, report)
        raise ValueError('final publication scan failed; see preparation-report.json')
    save(marker, report)
    print(json.dumps({'status': report['status'], 'directory': dest.relative_to(ROOT).as_posix(),
                      'source_files': report['source_files'], 'assets': assets, 'privacy_scan': scan['status'],
                      'portable_checks': 'passed', 'uploaded': False}, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT/'work/github-publication-v0.1')
    parser.add_argument('--refresh', action='store_true', help='replace only a previous managed local publication copy')
    parser.add_argument('--sdrpp-root', type=Path, default=Path('D:/Tools/sdrpp_windows_x64'), help='optional matching runtime for offline DLL/FFT checks, never modified')
    args = parser.parse_args()
    prepare(args.output_dir, args.refresh, args.sdrpp_root)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
