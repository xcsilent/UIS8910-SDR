"""Offline checks of publication redaction and nested/binary privacy scanning."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_release import ROOT, Redactor, load, save, scrub_diagnostic_path


def check_diagnostic_copy(base):
    # Minimal PE32+ fixture: executable code and read-only diagnostic data.
    data = bytearray(1536)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<H', data, 0x86, 2)
    struct.pack_into('<H', data, 0x94, 0xf0)
    optional = 0x98
    struct.pack_into('<H', data, optional, 0x20b)
    for i, (name, offset, flags) in enumerate(((b'.text', 512, 0x60000020),
                                              (b'.rdata', 1024, 0x40000040))):
        at = optional+0xf0+40*i
        data[at:at+len(name)] = name
        struct.pack_into('<II', data, at+16, 512, offset)
        struct.pack_into('<I', data, at+36, flags)
    data[512:1024] = b'X'*512
    marker = str(ROOT).encode('utf-16-le')
    data[1056:1056+len(marker)] = marker
    path = base/'fixture.dll'
    path.write_bytes(data)
    report = scrub_diagnostic_path(path)
    after = path.read_bytes()
    assert report['modified'] and report['length_unchanged']
    assert report['patches'] == [{'offset': 1056, 'bytes': len(marker), 'section': '.rdata',
                                  'purpose': 'diagnostic source path prefix only'}]
    assert len(after) == len(data) and after[:1056] == data[:1056]
    assert after[1056+len(marker):] == data[1056+len(marker):]
    assert marker not in after
    # Reject signed images and writable sections without mutating the file.
    signed = bytearray(data)
    struct.pack_into('<II', signed, optional+112+8*4, 1, 1)
    writable = bytearray(data)
    struct.pack_into('<I', writable, optional+0xf0+40+36, 0xc0000040)
    for unsafe in (signed, writable):
        path.write_bytes(unsafe)
        try:
            scrub_diagnostic_path(path)
        except ValueError:
            pass
        else:
            raise AssertionError('unsafe diagnostic rewrite accepted')
        assert path.read_bytes() == unsafe
    path.unlink()


def verify():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        path = base/'summary.json'
        synthetic = 'SYNTH_DEVICE_01234'
        save(path, {'serial': synthetic, 'rate_hz': 1920000,
                    'command': '--serial '+synthetic+' --file '+str(ROOT/'work/input.fc32'),
                    'path': 'C:/home/USER',
                    'upstream_credit': 'Copyright upstream@example.org',
                    'mock_code': 'Serial=lambda *a: None'})
        r = Redactor([path])
        assert r.sanitize(path)
        row = load(path)
        assert synthetic not in path.read_text(encoding='utf-8')
        assert 'PrivateTest' not in row['path']
        assert row['rate_hz'] == 1920000
        assert row['upstream_credit'] == 'Copyright upstream@example.org'
        assert row['mock_code'] == 'Serial=lambda *a: None'
        assert r.scan(base)['status'] == 'passed'
        check_diagnostic_copy(base)
        # Scan inside an archive and UTF-16 data, not only top-level JSON text.
        with zipfile.ZipFile(base/'nested.zip', 'w') as z:
            z.writestr('binary.dat', synthetic.encode('utf-16-le'))
            z.writestr('capture.raw', b'1234')
            z.writestr(synthetic+'.txt', b'harmless content')
            z.writestr('.codex/config.json', b'{}')
        result = r.scan(base)
        assert result['status'] == 'failed'
        kinds = {item['category'] for item in result['findings']}
        assert {'known_personal_marker', 'personal_marker_in_filename',
                'excluded_payload_or_private_directory'} <= kinds
        assert synthetic not in json.dumps(result)
    return {'status': 'passed', 'device_accessed': False,
            'checks': ['structured_and_embedded_device_id', 'home_and_workspace_paths',
                       'numerical_evidence_and_upstream_attribution_preserved',
                       'nested_zip_utf16_marker', 'nested_capture_rejected',
                       'nested_private_directory_and_identifier_filename',
                       'diagnostic_rewrite_preserves_executable_and_layout',
                       'signed_and_writable_rewrite_rejected', 'no_secret_in_findings']}


if __name__ == '__main__':
    print(json.dumps(verify()))
