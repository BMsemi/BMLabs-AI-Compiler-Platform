"""Real bounded execution with durable evidence and fail-closed finalization."""
import hashlib
import json
import sys
from pathlib import Path
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from compiler.execution import run_command, write_json
from compiler.inventory import probe
from compiler.supported_model import validate_ir
from compiler.synthesis import tool_command, run_synthesis
from .artifacts import save_artifact
from .models import BuildJob, BuildLog, BuildStage, Artifact, IRVersion, RTLRevision, VerificationRun


class BuildCancelled(Exception):
    pass


def claim_next():
    for pk in BuildJob.objects.filter(status='queued', cancel_requested=False).order_by('created_at').values_list('pk', flat=True)[:20]:
        if BuildJob.objects.filter(pk=pk, status='queued', cancel_requested=False).update(
                status='running', started_at=timezone.now(), reason='Executing real compiler stages.'):
            return BuildJob.objects.get(pk=pk)
    return None


def check_cancel(build):
    if BuildJob.objects.filter(pk=build.pk, cancel_requested=True).exists():
        raise BuildCancelled('Cancelled at a stage boundary; completed process evidence was retained.')


def persist_files(build, work):
    artifacts = {}
    files = [p for p in sorted(work.iterdir()) if p.is_file() and p.name not in {'input.py', 'execution_manifest.json'}]
    total = sum(p.stat().st_size for p in files)
    if total > settings.COMPILER_MAX_ARTIFACT_BYTES:
        raise ValueError(f'Artifacts exceed the {settings.COMPILER_MAX_ARTIFACT_BYTES}-byte quota; retained in {work}')
    for path in files:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        kind = 'bitstream' if path.suffix in ('.bin','.bit') else 'rtl' if path.suffix == '.v' else 'log' if path.suffix == '.log' else 'ir' if path.name == 'ir.json' else 'report'
        artifacts[path.name] = build.artifacts.filter(name=path.name, sha256=digest).first() or save_artifact(build, path.name, data, kind)
    return artifacts


def finalize(build, work, evidence, checks, graph=None):
    """Publish the manifest last; storage failure never leaves a success status."""
    try:
        from compiler.artifact_packaging import compress_diagnostics
        compress_diagnostics(work)
        artifacts = persist_files(build, work)
        rtl = None
        if graph is not None and 'ir.json' in artifacts:
            ir = IRVersion.objects.create(build=build, schema_version='bmlabs.linear-int8.v1', graph=graph, artifact=artifacts['ir.json'])
            if 'model.v' in artifacts:
                rtl = RTLRevision.objects.create(build=build, ir=ir, artifact=artifacts['model.v'], provider='BM Labs bounded Linear emitter v1')
        for stage, report in checks:
            VerificationRun.objects.create(build=build, rtl=rtl, stage=stage, status=report['status'], report=report)
        with transaction.atomic():
            current = BuildJob.objects.select_for_update().get(pk=build.pk)
            if current.cancel_requested:
                build.status = 'cancelled'
                build.reason = 'Cancelled; completed process results and artifacts were retained.'
            manifest = {'build_id': str(build.pk), 'status': build.status, 'reason': build.reason,
                'commands': evidence, 'artifacts': {name: {'sha256': a.sha256, 'path': a.file.name} for name, a in artifacts.items()}}
            write_json(work/'execution_manifest.json', manifest)
            save_artifact(build, 'execution_manifest.json', (work/'execution_manifest.json').read_bytes())
            build.completed_at = timezone.now()
            build.save(update_fields=['status', 'reason', 'completed_at'])
    except Exception as exc:
        build.status = 'failed'
        build.reason = f'{build.reason} Artifact persistence failed: {exc}. Work directory: {work}'
        build.completed_at = timezone.now()
        build.save(update_fields=['status', 'reason', 'completed_at'])
        write_json(work/'execution_manifest.json', {'build_id': str(build.pk), 'status': 'failed', 'reason': build.reason, 'commands': evidence})
        BuildLog.objects.create(build=build, stage='artifacts', level='error', message=build.reason)
    return build


def recover_interrupted():
    """Called only while holding the exclusive single-host worker lock."""
    for job in BuildJob.objects.filter(status='running'):
        job.status = 'cancelled' if job.cancel_requested else 'failed'
        job.reason = 'Worker interrupted. Partial artifacts recovered; request a new build.'
        job.stages.filter(status='running').update(status='failed', evidence={'error': 'Worker interrupted', 'exit_code': None})
        work = Path(settings.MEDIA_ROOT)/'work'/str(job.pk)
        if work.is_dir():
            if job.configuration.get('pipeline') == 'fabulous-reference-v1' and settings.FABULOUS_WORK_ROOT:
                from compiler.fabulous_reference import archive_project
                try:
                    archive_project(Path(settings.FABULOUS_WORK_ROOT)/str(job.pk), work)
                except Exception as exc:
                    BuildLog.objects.create(build=job, stage='recovery', level='error',
                        message=f'Reference files remain in the configured Linux work directory: {exc}')
            finalize(job, work, list(job.stages.values('name', 'status', 'evidence')), [])
        else:
            job.completed_at = timezone.now()
            job.save(update_fields=['status', 'reason', 'completed_at'])
        BuildLog.objects.create(build=job, stage='worker', level='error', message=job.reason)


def execute(build):
    if build.status != 'running':
        raise ValueError('Job must first be claimed.')
    work = Path(settings.MEDIA_ROOT)/'work'/str(build.pk)
    work.mkdir(parents=True, exist_ok=False)
    evidence, checks = [], []
    graph = None
    pipeline = build.configuration.get('pipeline')

    def command(name, argv, timeout=120, *, cleanup=False):
        if not cleanup:check_cancel(build)
        stage = BuildStage.objects.create(build=build, name=name)
        result = run_command(argv, work, timeout)
        result['stage'] = name
        evidence.append(result)
        stage.evidence = result
        stage.status = 'successful' if result['successful'] else 'failed'
        stage.save()
        write_json(work/(name+'.execution.json'), result)
        for stream in ('stdout', 'stderr'):
            (work/(name+'.'+stream+'.log')).write_text(result[stream], encoding='utf-8')
        BuildLog.objects.create(build=build, stage=name, level='info' if result['successful'] else 'error',
            message=f"exit={result['exit_code']} duration={result['duration_seconds']}s; {result.get('error', '')}")
        if not result['successful']:
            raise RuntimeError(f"{name} failed (exit {result['exit_code']}): {result.get('error') or result['stderr'][-1500:] or result['stdout'][-1500:]}")
        if not cleanup:check_cancel(build)
        return result

    try:
        check_cancel(build)
        if pipeline == 'sky130-counter-v1':
            if not settings.COMPILER_ENABLED:
                raise ValueError('Execution disabled.')
            from compiler.sky130_runtime import run
            report=run(work,command,build.configuration['profile_sha256'])
            for entry in report['commands']:
                result=json.loads((work/('sky130_'+entry['evidence'])).read_text())
                BuildStage.objects.create(build=build,name='sky130_'+entry['stage'],
                    status='successful' if result['successful'] else 'failed',evidence=result)
            build.status='succeeded'
            build.reason='Upstream SKY130 counter synthesized, placed/routed and converted to FASM, binary and hex. File framing verified. Timing closure and hardware execution remain unverified.'
            return finalize(build,work,evidence,checks)
        if pipeline == 'zcu106-preflight-v1':
            if not settings.COMPILER_ENABLED:
                raise ValueError('Execution disabled.')
            from compiler.physical_target import run
            run(work, command, build.configuration['config_sha256'])
            build.status = 'succeeded'
            build.reason = 'ZCU106 board identity, PYNQ runtime and installed overlay hashes verified. No programming or numerical test executed.'
            return finalize(build, work, evidence, checks)
        if not settings.COMPILER_ENABLED or pipeline not in ('linear-int8-v1', 'linear-synth-v1', 'linear-fpga-v1', 'x2-candidate-v1', 'fabulous-reference-v1'):
            raise ValueError('Execution disabled or unsupported pipeline.')
        # Validate the immutable source before invoking even dependency probes.
        if pipeline not in ('x2-candidate-v1', 'fabulous-reference-v1'):
            source = Artifact.objects.get(pk=build.configuration['input_artifact'], build=build, kind='source')
            with source.file.open('rb') as handle:
                data = handle.read(65537)
            if hashlib.sha256(data).hexdigest() != source.sha256:
                raise ValueError('Immutable source snapshot failed integrity validation.')
            (work/'input.py').write_bytes(data)
        inventory = probe()
        write_json(work/'tool_inventory.json', inventory)
        for name, result in inventory['tools'].items():
            BuildStage.objects.create(build=build, name='probe_'+name,
                status='successful' if result['successful'] else 'unavailable', evidence=result)
        check_cancel(build)
        if pipeline == 'fabulous-reference-v1':
            from compiler.fabulous_reference import run
            if not inventory.get('fabulous_tools_ready'):
                raise RuntimeError('FABulous reference runtime probes failed. See tool_inventory.json.')
            report = run(work, command)
            checks.append(('fabric_reference', report))
            build.reason = 'Upstream reference bitstream generated and loaded into fabric RTL; 100 comparisons passed. No BM target or X2 binding.'
        elif pipeline == 'x2-candidate-v1':
            from compiler.x2_verification import run
            report = run(work, command, patched=True)
            checks.append(('x2_candidate', report))
            write_json(work/'verification.json', report)
            build.reason = f"Candidate X2 scoreboard passed {report['checks']} comparisons; upstream source preserved. No finalized ABI or FABulous co-simulation."
        else:
            if not inventory['linear_ready']:
                raise RuntimeError('Required repository files, Torch runtime, Icarus or vvp are unavailable. See tool_inventory.json.')
            if pipeline in ('linear-synth-v1','linear-fpga-v1') and not inventory.get('synthesis_ready'):
                raise RuntimeError('Yosys is unavailable; synthesis pipeline cannot execute.')
            scripts = settings.BASE_DIR/'compiler'
            write_json(work/'adapter_sources.json', {name: hashlib.sha256((scripts/name).read_bytes()).hexdigest()
                for name in ['repository_bridge.py', 'supported_model.py', 'rtl_backend.py', 'rtl_oracle.py', 'logical_pe.py', 'artifact_packaging.py', 'execution.py', 'synthesis.py']})
            command('graph_ir_planning', [settings.COMPILER_PYTHON, '-I', '-B', str(scripts/'repository_bridge.py'),
                '--repo', settings.COMPILER_MODEL_REPO, '--input', str(work/'input.py'), '--out', str(work)], 180)
            candidate = json.loads((work/'ir.json').read_text(encoding='utf-8'))
            validate_ir(candidate)
            graph = candidate
            command('generate_verilog', [sys.executable, '-I', '-B', str(scripts/'rtl_backend.py'), '--ir', str(work/'ir.json'), '--out', str(work/'model.v')])
            command('generate_oracle', [sys.executable, '-I', '-B', str(scripts/'rtl_oracle.py'), '--ir', str(work/'ir.json'), '--out', str(work)])
            command('iverilog_compile', tool_command('IVERILOG', ['-g2012', '-Wall', '-s', 'tb', '-o', 'simulation.vvp', 'model.v', 'tb.v'], work), 90)
            simulation = command('rtl_simulation', tool_command('VVP', ['simulation.vvp'], work), 90)
            plan = json.loads((work/'verification_plan.json').read_text())
            marker = f"BMLABS_RTL_PASS vectors={plan['vectors']} outputs={plan['outputs']}"
            if marker not in simulation['stdout'].splitlines():
                raise RuntimeError('Simulator exited without the required numerical verification completion marker.')
            verification = {'status': 'passed', 'marker': marker, **plan,
                'scope': 'Generic Linear RTL against independent integer oracle; no physical hardware binding.'}
            checks.append(('rtl', verification))
            pe = command('logical_pe_simulation', [settings.COMPILER_PYTHON, '-I', '-B', str(scripts/'logical_pe.py'),
                '--repo', settings.COMPILER_MODEL_REPO, '--ir', str(work/'ir.json'),
                '--vectors', str(work/'vectors.json'), '--out', str(work)], 120)
            pe_marker = f"BMLABS_LOGICAL_PE_PASS vectors={plan['vectors']} outputs={plan['outputs']}"
            if pe_marker not in pe['stdout'].splitlines():
                raise RuntimeError('Logical PE exited without its numerical verification completion marker.')
            pe_report = json.loads((work/'logical_pe_verification.json').read_text())
            if (pe_report.get('status') != 'passed' or pe_report.get('physical_hardware') is not False
                    or pe_report.get('vectors') != plan['vectors'] or pe_report.get('outputs') != plan['outputs']
                    or pe_report.get('comparisons') != plan['vectors'] * plan['outputs']
                    or pe_report.get('geometry') != {'rows': 32, 'cols': 32}):
                raise RuntimeError('Logical PE report failed validation.')
            checks.append(('logical_pe', pe_report))
            if pipeline in ('linear-synth-v1','linear-fpga-v1'):
                netlist = run_synthesis(work, command)
                if marker not in netlist['stdout'].splitlines():
                    raise RuntimeError('Synthesized netlist did not pass the independent numerical scoreboard.')
                checks.extend([('equivalence', {'status': 'passed', 'scope': 'ABC CEC formal output equivalence of Yosys-lowered RTL and synthesized netlist; matching complete AIG interfaces'}),
                               ('rtl_netlist', {**verification, 'scope': 'Synthesized netlist vs independent integer oracle'})])
            if pipeline == 'linear-fpga-v1':
                from compiler.physical_linear import execute as execute_physical
                report = execute_physical(work,command,build.configuration['config_sha256'])
                checks.append(('physical_fpga',report))
            write_json(work/'verification.json', {'status': 'passed', 'checks': [{'stage': s, **r} for s, r in checks]})
            build.reason = f"Verified RTL and logical 32x32 PE: {plan['vectors']} vectors / {plan['outputs']} outputs" + ('; synthesis, equivalence and netlist simulation passed.' if pipeline == 'linear-synth-v1' else '.')
            if pipeline == 'linear-fpga-v1':
                build.reason = f"Compiler, synthesis and physical FPGA verification passed: {report['vectors']} vectors, {report['model_comparisons']} outputs. Pinned Qwen6 overlay programmed; PL MVM and PS bias/ReLU."
        build.status = 'succeeded'
    except BuildCancelled as exc:
        build.status, build.reason = 'cancelled', str(exc)
        write_json(work/'cancellation.json', {'status': 'cancelled', 'reason': str(exc)})
    except Exception as exc:
        build.status, build.reason = 'failed', f'{type(exc).__name__}: {exc}'
        if evidence and evidence[-1].get('successful'):
            # Exit zero is process evidence, not proof that its output passed the
            # stage's semantic checks (ABC also exits zero on non-equivalence).
            last_result = evidence[-1]
            last_result['validation_successful'] = False
            last_result['validation_error'] = build.reason
            build.stages.filter(name=last_result['stage']).update(status='failed', evidence=last_result)
            write_json(work/(last_result['stage']+'.execution.json'), last_result)
        BuildLog.objects.create(build=build, stage='pipeline', level='error', message=build.reason)
        write_json(work/'failure.json', {'status': 'failed', 'reason': build.reason})
        last = evidence[-1]['stage'] if evidence else ''
        failed_check = ('physical_fpga' if last.startswith('zcu106_') and pipeline == 'linear-fpga-v1' else
                        'fabric_reference' if pipeline == 'fabulous-reference-v1' else
                        'x2_candidate' if pipeline == 'x2-candidate-v1' else
                        'logical_pe' if last == 'logical_pe_simulation' else
                        'equivalence' if last == 'abc_equivalence' or last.endswith('_aig') else
                        'rtl_netlist' if last.startswith('netlist_') else 'rtl')
        if pipeline != 'zcu106-preflight-v1' and not any(stage == failed_check and report['status'] == 'passed' for stage, report in checks):
            checks.append((failed_check, {'status': 'failed', 'reason': build.reason}))
    return finalize(build, work, evidence, checks, graph)
