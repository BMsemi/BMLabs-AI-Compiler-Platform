"""Model-specific FABulous bitstream and native X2 co-simulation prototype."""
import hashlib,json,shutil,uuid
from pathlib import Path
from django.conf import settings
from .fabric_postprocess import emit
from .fabulous_runtime import command,path_for_runtime
from .execution import write_json


def configuration():
    path=settings.BASE_DIR/'deploy/fabric-postprocess-v1.json'
    profile=json.loads(path.read_text(encoding='utf-8'))
    package=path.with_name(profile['package'])
    if profile.get('schema')!='bmlabs.fabric-postprocess.v1' or hashlib.sha256(package.read_bytes()).hexdigest()!=profile['package_sha256']:
        raise ValueError('Missing or changed FABulous prototype source package')
    return path,profile


def run(work,execute,expected_hash):
    path,profile=configuration()
    profile_bytes=path.read_bytes()
    if hashlib.sha256(profile_bytes).hexdigest()!=expected_hash:raise ValueError('Fabric profile changed since queueing')
    profile=json.loads(profile_bytes)
    project=Path(settings.FABULOUS_WORK_ROOT)/str(uuid.UUID(work.name))
    expected=Path('//wsl.localhost/'+settings.FABULOUS_RUNTIME['distro']+'/home/'+settings.FABULOUS_RUNTIME.get('user','bmlabs')+'/work')
    if not project.is_relative_to(expected) or any(c.isspace() for c in str(project)):
        raise ValueError('Invalid FABulous prototype work directory')
    ir=json.loads((work/'ir.json').read_text(encoding='utf-8'))
    vectors=json.loads((work/'vectors.json').read_text())
    (work/'fabric_model.v').write_text(emit(ir),encoding='utf-8')
    shutil.copyfile(settings.BASE_DIR/'compiler/rtl/fabric_cosim_tb.v.in',work/'fabric_cosim_template.v.in')
    # Freeze the profile metadata before the Linux bridge reads it.
    snapshot=work/'fabric_profile_snapshot.json';snapshot.write_bytes(profile_bytes)
    shutil.copyfile(path.with_name(profile['package']),work/profile['package'])
    if hashlib.sha256((work/profile['package']).read_bytes()).hexdigest()!=profile['package_sha256']:
        raise ValueError('Fabric source package changed while being snapshotted')
    def bridge(stage,timeout=90,cleanup=False):
        return execute('fabric_'+stage,command('python',[path_for_runtime(settings.BASE_DIR/'compiler/fabric_bridge.py'),
            stage,'--work',path_for_runtime(work),'--project',path_for_runtime(project),'--profile',path_for_runtime(snapshot)],timeout=timeout),timeout+20,cleanup=cleanup)
    prepared=False
    try:
        bridge('prepare');prepared=True
        for stage,flag in [('synthesis','--synth-only'),('place_route','--pnr-only'),('bitstream','--bitgen-only')]:
            execute('fabric_'+stage,command('FABulous',['-p',path_for_runtime(project),'run',
                'compile_design '+flag+' user_design/model_postprocess.v'],timeout=240),260)
        bridge('cosim')
        cwd=project/'Test/prototype'
        execute('fabric_iverilog',command('iverilog',['-g2012','-s','prototype_tb','-o','prototype.vvp','-f','sources.f'],cwd=cwd,timeout=240),260)
        result=execute('fabric_simulation',command('vvp',['-n','prototype.vvp'],cwd=cwd,timeout=900),920)
        comparisons=len(vectors)*len(ir['weights'])
        marker=f'BMLABS_X2_FABRIC_COSIM_PASS comparisons={comparisons} vectors={len(vectors)}'
        if marker not in result['stdout'].splitlines():raise ValueError('Missing full numerical co-simulation completion marker')
        report={'status':'passed','vectors':len(vectors),'comparisons':comparisons,'physical_hardware':False,
            'scope':'Native X2 MVM RTL plus model-specific FABulous bias/ReLU configuration, loaded through the AXI shell configuration port in RTL simulation.',
            'fabric_profile_sha256':expected_hash,'fabric_package_sha256':profile['package_sha256']}
        write_json(work/'fabric_model_verification.json',report)
        return report
    finally:
        if prepared:bridge('collect',180,cleanup=True)
