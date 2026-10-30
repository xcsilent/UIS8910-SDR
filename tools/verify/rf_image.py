"""Resolve current PAC RF decode evidence, without treating it as live RAM."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def current_pac_image():
    image=ROOT/'work/rf-cache/current-rf-decoded.bin'
    evidence=ROOT/'records/rf/reference-rf-pac-payload.json'
    manifest=ROOT/'outputs/firmware/current/manifest.json'
    report=json.loads(evidence.read_text())
    installed=json.loads(manifest.read_text())['installed_firmware']
    assert report['status']=='passed' and report['decompressed'] and report['sdk_roundtrip_verified']
    assert report['pac_sha256']==installed['sha256']
    assert hashlib.sha256(image.read_bytes()).hexdigest()==report['decoded_sha256']
    pac=ROOT/installed['pac']
    assert hashlib.sha256(pac.read_bytes()).hexdigest()==installed['sha256']
    dependencies=[Path(__file__),evidence,manifest,pac]
    for name,digest in report['dependencies'].items():
        path=ROOT/name
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest,name
        dependencies.append(path)
    return image,list(dict.fromkeys(dependencies))
