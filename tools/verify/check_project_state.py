"""Read-only checks for the current project, not a replay of historical trials."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from sdr.capture_layout import current as capture_layout


def require(ok,message):
    if not ok:
        raise ValueError(message)


def local(relative):
    path=(ROOT/relative.replace('\\','/')).resolve()
    require(path.is_relative_to(ROOT) and path.exists(),'missing or escaping path: '+relative)
    return path


def read(relative):
    return json.loads(local(relative).read_text(encoding='utf-8'))


def sha(relative):
    return hashlib.sha256(local(relative).read_bytes()).hexdigest()


def evidence_freshness(relative):
    """Compare saved input identities, without rerunning tests or reading IQ.

    A matching snapshot does not prove coverage or hardware behavior. Missing
    regenerable work files make evidence unverifiable, not a new test failure.
    """
    report=read(relative)
    fingerprints=report.get('dependencies',report.get('sources',report.get('source_sha256',{})))
    if isinstance(fingerprints,list):
        fingerprints={row['path']:row['sha256'] for row in fingerprints}
    # Build records also identify output objects; test records may identify
    # the verifier independently from the input manifest.
    fingerprints=dict(fingerprints)
    if 'object' in report and 'object_sha256' in report:
        fingerprints[report['object']]=report['object_sha256']
    for item in report.get('artifacts',[]):
        fingerprints[item['path']]=item['sha256']
    if 'elf' in report and 'elf_sha256' in report:
        fingerprints[report['elf']]=report['elf_sha256']
    if 'pac' in report and 'sha256' in report:
        fingerprints[report['pac']]=report['sha256']
    changed=[]
    missing=[]
    for name,digest in fingerprints.items():
        path=(ROOT/name.replace('\\','/')).resolve()
        require(path.is_relative_to(ROOT),'evidence input escapes project: '+name)
        if not path.is_file():
            missing.append(name)
        elif hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            changed.append(name)
    return dict(report=relative,recorded_status=report.get('status'),
                input_count=len(fingerprints),changed_inputs=changed,missing_inputs=missing,
                freshness='stale' if changed else 'unverifiable' if missing or not fingerprints else 'matches_recorded_inputs',
                proves_current_hardware=False)


def check():
    state=read('docs/project-state.json')
    require(state['schema_version']==2,'unsupported state schema')
    firmware=state['installed_firmware']
    require(sha(firmware['pac'])==firmware['sha256'],'installed PAC changed')
    manifest=read(state['current_artifact_manifest'])
    require(manifest['installed_firmware']==firmware,'firmware pointer and state differ')
    for row in manifest['artifacts']:
        require(sha(row['path'])==row['sha256'],'current artifact changed: '+row['path'])
    pending=state.get('pending_flash')
    if pending:
        require(pending['pac']!=firmware['pac'],'candidate overwrites installed firmware')
        require(sha(pending['pac'])==pending['sha256'],'pending PAC changed')
    host=read(state['sdr_delivery']['host_manifest'])
    for row in host['artifacts']:
        require(sha(row['path'])==row['sha256'],'host artifact changed: '+row['path'])
    for command in read(state['capture_build_recipe'])['commands']:
        for arg in command:
            if isinstance(arg,dict) and not arg['path'].startswith('work/'):
                local(arg['path'])
    for name in ('application_crc','payload_hash','data_headers','per_packet_ack','application_retry'):
        require(state['sdr_delivery'][name] is False,'raw stream policy changed: '+name)
    require(state['sdr_delivery']['partial_corruption_accepted'] and
            state['sdr_delivery']['block_loss_accepted'],'accepted IQ loss policy missing')
    links=0
    for relative in state['active_documents']:
        path=local(relative)
        for target in re.findall(r'\]\(([^)]+)\)',path.read_text(encoding='utf-8')):
            target=target.strip('<>').split('#',1)[0]
            if not target or '://' in target or target.startswith('mailto:'):
                continue
            resolved=(path.parent/unquote(target)).resolve()
            require(resolved.is_relative_to(ROOT) and resolved.exists(),
                    'broken current link: '+relative+' -> '+target)
            links+=1
    python_files=list((ROOT/'tools').rglob('*.py'))
    for path in python_files:
        ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
    for path in read('inputs/manifest.json')['paths'].values():
        local(path)
    extracts=read('inputs/reference-source/predecessors/source-manifest.json')['files']
    for row in extracts:
        require(sha(row['path'])==row['sha256'],'reference excerpt changed: '+row['path'])
    platform=read('firmware/platform/air724ug.json')
    require(local('VERSION').read_text(encoding='utf-8').strip()==platform['version']==manifest['release_version'],
            'release version and build platform differ')
    require(platform['base_pac']==firmware['pac'] and platform['base_sha256']==firmware['sha256'],
            'firmware build platform differs from v0.1 release')
    for bundle in read('build-support/manifest.json')['bundles']:
        require(sha(bundle['path'])==bundle['sha256'],'bundled build dependency changed: '+bundle['path'])
    evidence=[evidence_freshness(row) for row in state.get('validation_evidence',[])]
    freshness='not_configured' if not evidence else 'stale' if any(r['freshness']=='stale' for r in evidence) else (
        'unverifiable' if any(r['freshness']=='unverifiable' for r in evidence) else 'matches_recorded_inputs')
    build=read(firmware['build_evidence'])
    cp=read(build['cp_modules'])
    require(cp['generation']==firmware['running_generation'],'installed CP generation differs')
    require(cp['slot_bytes']==firmware['slot_bytes'],'installed slot geometry differs')
    for key in ('resident','control'):
        require(sha(cp[key]['path'])==cp[key]['sha256'],'retained deployed CP artifact changed: '+key)
    require(sha(build['elf'])==build['elf_sha256'],'retained deployed AP ELF changed')
    # The B5 recipe is a retained offline baseline, not deployed service layout.
    baseline_layout=capture_layout()
    archive=local(state['cleanup']['archive_root'])
    return dict(status='passed',scope='Current structure, raw policy, release/host identities, local links and evidence freshness; no hardware or code tests',
                device_accessed=False,physical_archive=archive.relative_to(ROOT).as_posix(),
                active_documents=len(state['active_documents']),active_links=links,
                active_python_files=len(python_files),current_artifacts_verified=len(manifest['artifacts']),
                host_artifacts_verified=len(host['artifacts']),reference_excerpts_verified=len(extracts),
                code_evidence_freshness=freshness,code_evidence=evidence,
                retained_B5_recipe_layout=baseline_layout,installed_generation=cp['generation'],
                installed_slot_bytes=cp['slot_bytes'],historical_full_trial_chain_required=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:
        result=check()
    except (ValueError,KeyError,TypeError,OSError,SyntaxError) as error:
        result=dict(status='failed',error=str(error),device_accessed=False)
    encoded=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output:
        args.output.write_text(encoded,encoding='utf-8')
    print(encoded,end='')
    return int(result['status']!='passed')


if __name__=='__main__':
    sys.exit(main())
