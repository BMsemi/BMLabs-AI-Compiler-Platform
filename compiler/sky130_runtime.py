"""Web worker bridge for the pinned upstream SKY130 counter qualification flow."""
import hashlib
import json
import shutil
from pathlib import Path
from django.conf import settings
from .execution import wsl_path
from .sky130_user_design import REVISION

PIPELINE='sky130-counter-v1'


def configuration():
    path=settings.BASE_DIR/'deploy/sky130-user-design.json'
    profile=json.loads(path.read_text(encoding='utf-8'))
    if profile.get('revision')!=REVISION or profile.get('schema')!='bmlabs.sky130-toolchain.v1':
        raise ValueError('Unsupported SKY130 source/toolchain profile')
    for key in ('distro','user','repository','tool_path'):
        if not isinstance(profile.get(key),str) or not profile[key]:
            raise ValueError('Missing SKY130 configuration: '+key)
    return path,profile


def run(work,execute,expected_hash):
    path,profile=configuration()
    frozen=path.read_bytes()
    if hashlib.sha256(frozen).hexdigest()!=expected_hash:
        raise ValueError('SKY130 profile changed after queueing')
    profile=json.loads(frozen)
    (work/'sky130_profile.json').write_bytes(frozen)
    output=work/'sky130-output'
    try:
        execute('sky130_counter',['wsl.exe','-d',profile['distro'],'-u',profile['user'],
            '--cd',wsl_path(settings.BASE_DIR),'--exec','/usr/bin/python3','-m','compiler.sky130_user_design',
            '--repo',profile['repository'],'--output',wsl_path(output),
            '--design','counter','--tool-path',profile['tool_path']],2600)
    finally:
        if output.is_dir():
            for source in output.iterdir():
                if source.is_file():shutil.copyfile(source,work/('sky130_'+source.name))
    report=json.loads((work/'sky130_report.json').read_text())
    if report.get('status')!='successful' or report.get('hardware_verified') is not False:
        raise ValueError('SKY130 build evidence did not establish the expected compile-only result')
    for item in report['artifacts']:
        artifact=work/('sky130_'+item['path'])
        if artifact.parent!=work or hashlib.sha256(artifact.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('SKY130 artifact integrity mismatch')
    return report
