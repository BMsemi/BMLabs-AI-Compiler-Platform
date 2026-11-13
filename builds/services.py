from django.db import transaction
from audit.services import record
from projects.access import require_edit
from .models import BuildJob, BuildLog
from django.conf import settings
from compiler.supported_model import parse_source
from .artifacts import save_artifact
import hashlib

@transaction.atomic
def request_build(user, project, pipeline=None, entrypoint='model.py'):
    require_edit(user, project)
    configuration = project.configurations.order_by('-version').first()
    x2 = project.x2_configurations.order_by('-version').first()
    target = project.target
    snapshot = {} if not target else {key: getattr(target, key) for key in
        ['name', 'version', 'fabric_revision', 'status', 'source_url', 'source_commit', 'resources', 'constraints', 'bitstream_format']}
    reason = 'No supported pipeline selected. Choose linear-int8-v1 for generic RTL verification. No tools ran.'
    build = BuildJob.objects.create(project=project, requested_by=user, target=target,
        configuration=configuration.settings if configuration else {}, x2_abi_version=x2.abi_version if x2 else '',
        target_snapshot=snapshot, x2_snapshot={} if not x2 else {'version': x2.version, 'abi_version': x2.abi_version, 'status': x2.status, 'contract': x2.contract},
        input_manifest=[{'id': str(f.pk), 'name': f.name, 'sha256': f.sha256, 'size': f.size} for f in project.files.all()],
        status='blocked', reason=reason)
    BuildLog.objects.create(build=build, stage='preflight', level='warning', message=reason)
    if pipeline in ('linear-int8-v1', 'linear-synth-v1', 'linear-fpga-v1'):
        try:
            if not settings.COMPILER_ENABLED:
                raise ValueError('Compiler execution is disabled by the administrator.')
            if not settings.COMPILER_MODEL_REPO or not settings.COMPILER_PYTHON:
                raise ValueError('Compiler repository and Python runtime are not configured.')
            physical_config_hash = None
            if pipeline == 'linear-fpga-v1':
                from compiler.physical_target import configuration as physical_configuration, ADAPTER
                if not user.is_superuser:
                    raise ValueError('Only administrators can program the shared FPGA.')
                if not target or target.resources.get('adapter') != ADAPTER:
                    raise ValueError('Select the configured ZCU106 target.')
                path, hardware = physical_configuration()
                if hardware.get('programming_enabled') is not True:
                    raise ValueError('Physical programming has not been enabled by the administrator.')
                if BuildJob.objects.filter(status__in=['queued','running'],configuration__pipeline__in=['zcu106-preflight-v1','linear-fpga-v1']).exists():
                    raise ValueError('The shared FPGA already has a pending job.')
                physical_config_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if BuildJob.objects.filter(requested_by=user, status__in=['queued', 'running']).count() >= 5:
                raise ValueError('Five builds are already queued or running for this account. Wait for a build to finish.')
            source = project.files.filter(name=entrypoint).order_by('-created_at').first()
            if source is None:
                raise ValueError('Upload a supported model.py input (or select its exact entrypoint name).')
            with source.file.open('rb') as handle:
                data = handle.read(65537)
            if hashlib.sha256(data).hexdigest() != source.sha256:
                raise ValueError('Source integrity mismatch or input exceeds 64 KiB.')
            parse_source(data.decode('utf-8'))
            artifact = save_artifact(build, 'input.py', data, 'source')
            build.configuration = {**build.configuration, 'pipeline': pipeline,
                'entrypoint': entrypoint, 'input_artifact': str(artifact.pk),
                'logical_pe': {'rows': 32, 'cols': 32, 'physical_binding': False}}
            build.status = 'queued'
            build.reason = 'Queued for the Linear int8 pipeline. No hardware target or X2 ABI binding.'
            if physical_config_hash:
                build.configuration['config_sha256'] = physical_config_hash
                build.configuration['physical_adapter'] = ADAPTER
                build.x2_abi_version = 'qwen6-overlay-v1'
                build.reason = 'Queued compiler verification, pinned Qwen6 FPGA programming and physical model comparison. PL MVM; PS bias/ReLU.'
            build.compiler_version = pipeline
            build.ir_schema_version = 'bmlabs.linear-int8.v1'
            build.save()
            build.logs.all().delete()
            BuildLog.objects.create(build=build, stage='queue', message=build.reason)
        except (ValueError, UnicodeError, OSError, SyntaxError) as exc:
            build.reason = str(exc)
            build.status = 'failed'
            from django.utils import timezone
            build.completed_at = timezone.now()
            build.save()
            build.logs.all().delete()
            BuildLog.objects.create(build=build, stage='preflight', level='error', message=build.reason)
    elif pipeline == 'zcu106-preflight-v1':
        try:
            from compiler.physical_target import configuration, ADAPTER
            if not user.is_superuser:
                raise ValueError('Only administrators can access the shared physical board.')
            if not settings.COMPILER_ENABLED:
                raise ValueError('Compiler execution is disabled.')
            if not target or target.resources.get('adapter') != ADAPTER:
                raise ValueError('Select the configured ZCU106 physical target first.')
            if BuildJob.objects.filter(status__in=['queued','running'], configuration__pipeline__in=[pipeline,'linear-fpga-v1']).exists():
                raise ValueError('A physical board check is already pending.')
            path, config = configuration()
            build.configuration = {'pipeline':pipeline, 'config_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            build.status = 'queued'
            build.compiler_version = pipeline
            build.reason = 'Queued read-only ZCU106 identity, runtime and overlay integrity check. No programming or numerical test.'
            build.save()
            build.logs.all().delete()
            BuildLog.objects.create(build=build, stage='queue', message=build.reason)
        except (OSError, ValueError, KeyError) as exc:
            build.reason = str(exc)
            build.save(update_fields=['reason'])
    elif pipeline == 'sky130-counter-v1':
        try:
            from compiler.sky130_runtime import configuration
            if not user.is_superuser or not settings.COMPILER_ENABLED:
                raise ValueError('SKY130 qualification requires an administrator and enabled execution.')
            if BuildJob.objects.filter(status__in=['queued','running'],compiler_version=pipeline).exists():
                raise ValueError('A SKY130 qualification build is already pending.')
            path,profile=configuration()
            build.status='queued'
            build.compiler_version=pipeline
            build.configuration={'pipeline':pipeline,'profile_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            build.target=None
            build.target_snapshot={'name':'SKY130 classic_fabric_reram','version':profile['revision'][:12],
                'status':'reference','source_commit':profile['revision'],
                'source_url':'https://github.com/mole99/sky130-reram-fpga/tree/main/user_designs'}
            build.input_manifest=[]
            build.x2_snapshot={}
            build.x2_abi_version=''
            build.reason='Queued pinned upstream counter → Yosys → nextpnr → FASM → SKY130 fabric bitstream. Compile-only; no FPGA programming or timing-closure claim.'
            build.save()
            build.logs.all().delete()
            BuildLog.objects.create(build=build,stage='queue',message=build.reason)
        except (OSError,ValueError,KeyError) as exc:
            build.reason=str(exc)
            build.save(update_fields=['reason'])
    elif pipeline == 'fabulous-reference-v1':
        if settings.COMPILER_ENABLED and settings.FABULOUS_RUNTIME.get('distro') and settings.FABULOUS_WORK_ROOT and BuildJob.objects.filter(requested_by=user, status__in=['queued', 'running']).count() < 5:
            build.status = 'queued'
            build.compiler_version = pipeline
            build.configuration = {'pipeline': pipeline, 'scope': 'Upstream FABulous 2.2.0 reference counter only'}
            build.target = None
            build.target_snapshot = {'name': 'FABulous upstream reference', 'status': 'reference', 'version': '2.2.0'}
            build.x2_snapshot = {}
            build.x2_abi_version = ''
            build.reason = 'Queued reference-fabric synthesis, routing, binary generation and configured-fabric simulation. No BM hardware binding.'
            build.save()
            build.logs.all().delete()
            BuildLog.objects.create(build=build, stage='queue', message=build.reason)
        else:
            build.reason = 'FABulous reference runtime/work directory unconfigured, execution disabled, or five jobs already pending.'
            build.save(update_fields=['reason'])
    elif pipeline == 'x2-candidate-v1':
        from pathlib import Path
        if settings.COMPILER_ENABLED and settings.COMPILER_X1_REPO and Path(settings.COMPILER_X1_REPO).is_dir() and BuildJob.objects.filter(requested_by=user, status__in=['queued', 'running']).count() < 5:
            build.status = 'queued'
            build.compiler_version = pipeline
            build.configuration = {'pipeline': pipeline, 'contract': 'source-derived candidate, not finalized'}
            build.reason = 'Queued independent candidate X2 regression with a reviewable patch on a private source copy.'
            build.save()
            build.logs.all().delete()
            BuildLog.objects.create(build=build, stage='queue', message=build.reason)
        else:
            build.reason = 'Candidate X2 execution disabled, repository missing, or five jobs already pending.'
            build.save(update_fields=['reason'])
    elif pipeline:
        build.reason = f'Unsupported pipeline: {pipeline}. No tool was executed.'
        build.save(update_fields=['reason'])
    record(user, 'build.' + build.status, build, project=str(project.pk))
    return build


@transaction.atomic
def cancel_build(user, build):
    from django.core.exceptions import ValidationError
    from django.utils import timezone
    require_edit(user, build.project)
    build = BuildJob.objects.select_for_update().get(pk=build.pk)
    if build.status not in ('queued', 'running'):
        raise ValidationError('Only queued or running builds can be cancelled.')
    build.cancel_requested = True
    if build.status == 'queued':
        build.status = 'cancelled'
        build.completed_at = timezone.now()
        build.reason = 'Cancelled before execution.'
    else:
        build.reason = 'Cancellation requested; execution stops at the next bounded stage boundary.'
    build.save(update_fields=['cancel_requested', 'status', 'reason', 'completed_at'])
    BuildLog.objects.create(build=build, stage='cancel', message=build.reason)
    record(user, 'build.cancel_requested', build, project=str(build.project_id))
    return build
