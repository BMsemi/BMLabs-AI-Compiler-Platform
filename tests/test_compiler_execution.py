import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase, override_settings
from accounts.models import User
from builds.models import Artifact, BuildJob
from builds.services import request_build, cancel_build
from builds.runner import claim_next, execute, recover_interrupted
from compiler.execution import run_command
from compiler.supported_model import parse_source, validate_ir
from compiler.rtl_backend import emit
from projects.models import Project
from projects.services import store_input

SOURCE = b"MODEL = {'schema':'bmlabs.linear-int8.v1','weights':[[127,-2]],'bias':[-7],'relu':False}"


class InputAndProcessTests(SimpleTestCase):
    def test_rejects_executable_python(self):
        for source in ["import os\n" + SOURCE.decode(), "MODEL = __import__('os').system('echo BAD')",
                       SOURCE.decode() + '\nprint(MODEL)', SOURCE.decode().replace('127', 'True'),
                       SOURCE.decode().replace('127', '128')]:
            with self.subTest(source=source), self.assertRaises((ValueError, SyntaxError)):
                parse_source(source)

    def test_rejects_ir_with_floating_weights(self):
        spec = parse_source(SOURCE.decode())
        spec.update(input_dtype='int8', output_dtype='int32', weights=[[1.5]])
        with self.assertRaises(ValueError):
            validate_ir(spec)

    def test_process_failure_captures_both_streams(self):
        with tempfile.TemporaryDirectory() as cwd:
            result = run_command([sys.executable, '-I', '-c', 'import sys; print("out"); print("err",file=sys.stderr);sys.exit(7)'], cwd)
        self.assertEqual(result['exit_code'], 7)
        self.assertFalse(result['successful'])
        self.assertIn('out', result['stdout']); self.assertIn('err', result['stderr'])
        self.assertGreater(result['duration_seconds'], 0)

    def test_timeout_never_reports_success(self):
        with tempfile.TemporaryDirectory() as cwd:
            result = run_command([sys.executable, '-I', '-c', 'import time;time.sleep(15)'], cwd, timeout=0.3)
        self.assertTrue(result['timed_out'])
        self.assertFalse(result['successful'])

    def test_missing_executable_is_explicit(self):
        with tempfile.TemporaryDirectory() as cwd:
            result = run_command([str(Path(cwd)/'missing-tool.exe')], cwd)
        self.assertFalse(result['successful']); self.assertIsNone(result['exit_code'])
        self.assertIn('error', result)

    def test_fast_large_output_fails_even_if_process_exits_zero(self):
        with tempfile.TemporaryDirectory() as cwd:
            result = run_command([sys.executable, '-I', '-c', 'print("x"*100000)'], cwd, log_limit=1024)
        self.assertFalse(result['successful'])
        self.assertIn('Output limit', result['error'])


@override_settings(COMPILER_ENABLED=True, COMPILER_MODEL_REPO='configured-repository', COMPILER_PYTHON=sys.executable)
class BuildExecutionTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=Path(self.temp.name))
        self.settings_override.enable()
        self.addCleanup(self.temp.cleanup); self.addCleanup(self.settings_override.disable)
        self.user = User.objects.create_user('compiler@example.com', 'Tests-Only-Compiler-8712!', email_verified=True, is_active=True)
        self.project = Project.objects.create(name='Compiler test', owner=self.user)

    def queue(self):
        self.source = store_input(self.user, self.project, SimpleUploadedFile('model.py', SOURCE))
        return request_build(self.user, self.project, 'linear-int8-v1')

    def test_snapshot_is_immutable_and_job_claimed_once(self):
        build = self.queue()
        self.assertEqual(build.status, 'queued')
        Path(self.source.file.path).write_bytes(b'changed after queue')
        snapshot = build.artifacts.get(kind='source')
        self.assertEqual(Path(snapshot.file.path).read_bytes(), SOURCE)
        self.assertEqual(claim_next().pk, build.pk)
        self.assertIsNone(claim_next())

    def test_invalid_source_fails_before_execution(self):
        store_input(self.user, self.project, SimpleUploadedFile('model.py', b'import os'))
        build = request_build(self.user, self.project, 'linear-int8-v1')
        self.assertEqual(build.status, 'failed'); self.assertIsNone(build.started_at)
        self.assertFalse(build.stages.exists())

    def test_pending_builds_are_bounded(self):
        for _ in range(5):
            self.assertEqual(self.queue().status, 'queued')
        self.assertEqual(self.queue().status, 'failed')

    def test_source_tampering_fails(self):
        build = self.queue()
        Path(build.artifacts.get(kind='source').file.path).write_bytes(b'corrupted')
        build = execute(claim_next())
        self.assertEqual(build.status, 'failed')
        self.assertIn('integrity', build.reason)
        self.assertTrue(build.artifacts.filter(name='failure.json').exists())

    @patch('builds.runner.probe', return_value={'linear_ready': False, 'tools': {}})
    def test_missing_dependency_is_failed_with_inventory_artifact(self, probe):
        self.queue()
        build = execute(claim_next())
        self.assertEqual(build.status, 'failed')
        self.assertTrue(build.artifacts.filter(name='tool_inventory.json').exists())
        self.assertFalse(build.rtl_revisions.exists())

    def test_exit_zero_without_oracle_marker_does_not_succeed(self):
        self.queue()
        def fake_process(argv, work, timeout):
            # Controlled test double for missing completion evidence, not a compiler output.
            spec = parse_source(SOURCE.decode())
            spec.update(input_dtype='int8', output_dtype='int32')
            (work/'ir.json').write_text(json.dumps(spec))
            (work/'model.v').write_text(emit(spec))
            (work/'verification_plan.json').write_text(json.dumps({'vectors': 1, 'outputs': 1}))
            return {'argv': argv, 'exit_code': 0, 'successful': True, 'duration_seconds': .01, 'stdout': '', 'stderr': ''}
        with patch('builds.runner.probe', return_value={'linear_ready': True, 'tools': {}}), patch('builds.runner.run_command', side_effect=fake_process):
            build = execute(claim_next())
        self.assertEqual(build.status, 'failed')
        self.assertIn('completion marker', build.reason)
        self.assertEqual(build.verifications.get().status, 'failed')
        stage = build.stages.get(name='rtl_simulation')
        self.assertEqual(stage.status, 'failed')
        self.assertEqual(stage.evidence['exit_code'], 0)
        self.assertFalse(stage.evidence['validation_successful'])

    def test_logical_pe_exit_zero_without_marker_fails_after_rtl_pass(self):
        self.queue()
        def process(argv, work, timeout):
            # Test double deliberately omits PE verification, even with exit zero.
            spec = parse_source(SOURCE.decode())
            spec.update(input_dtype='int8', output_dtype='int32')
            (work/'ir.json').write_text(json.dumps(spec))
            (work/'model.v').write_text(emit(spec))
            (work/'verification_plan.json').write_text(json.dumps({'vectors': 1, 'outputs': 1}))
            return {'argv': argv, 'exit_code': 0, 'successful': True, 'duration_seconds': .01,
                    'stdout': 'BMLABS_RTL_PASS vectors=1 outputs=1\n', 'stderr': ''}
        with patch('builds.runner.probe', return_value={'linear_ready': True, 'tools': {}}), patch('builds.runner.run_command', side_effect=process):
            build = execute(claim_next())
        self.assertEqual(build.status, 'failed')
        self.assertEqual(build.verifications.get(stage='rtl').status, 'passed')
        self.assertEqual(build.verifications.get(stage='logical_pe').status, 'failed')
        self.assertFalse(build.stages.get(name='logical_pe_simulation').evidence['validation_successful'])

    def test_stage_evidence_and_artifacts_require_project_access(self):
        build = self.queue()
        outsider = User.objects.create_user('outsider-build@example.com', 'Tests-Only-Compiler-8712!', email_verified=True, is_active=True)
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(f'/api/v1/builds/{build.pk}/stages/').status_code, 404)
        artifact = build.artifacts.first()
        self.assertEqual(self.client.get(f'/api/v1/artifacts/{artifact.pk}/download/').status_code, 404)

    def test_queued_cancellation_prevents_claim(self):
        build = self.queue()
        self.assertEqual(cancel_build(self.user, build).status, 'cancelled')
        self.assertIsNone(claim_next())

    def test_running_cancellation_stops_before_tools(self):
        self.queue()
        build = claim_next()
        cancel_build(self.user, build)
        with patch('builds.runner.probe') as probe:
            build = execute(build)
        probe.assert_not_called()
        self.assertEqual(build.status, 'cancelled')
        self.assertTrue(build.artifacts.filter(name='cancellation.json').exists())

    def test_cancel_endpoint_requires_project_write_access(self):
        build = self.queue()
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(f'/api/v1/builds/{build.pk}/cancel/').status_code, 200)
        self.assertEqual(self.client.post(f'/api/v1/builds/{build.pk}/cancel/').status_code, 400)

    def test_interrupted_worker_recovers_partial_artifacts(self):
        self.queue()
        build = claim_next()
        work = Path(self.temp.name)/'work'/str(build.pk)
        work.mkdir(parents=True)
        (work/'partial.stdout.log').write_text('real work completed before interruption')
        recover_interrupted()
        build.refresh_from_db()
        self.assertEqual(build.status, 'failed')
        self.assertTrue(build.artifacts.filter(name='partial.stdout.log').exists())
        self.assertFalse(build.verifications.filter(status='passed').exists())

    @patch('builds.runner.probe', return_value={'linear_ready': False, 'tools': {}})
    def test_persistence_failure_cannot_leave_success_manifest(self, probe):
        self.queue()
        build = claim_next()
        with patch('builds.runner.save_artifact', side_effect=OSError('Disk unavailable')):
            build = execute(build)
        self.assertEqual(build.status, 'failed')
        manifest = json.loads((Path(self.temp.name)/'work'/str(build.pk)/'execution_manifest.json').read_text())
        self.assertEqual(manifest['status'], 'failed')

    @override_settings(COMPILER_MAX_ARTIFACT_BYTES=1)
    @patch('builds.runner.probe', return_value={'linear_ready': False, 'tools': {}})
    def test_artifact_quota_failure_is_visible(self, probe):
        self.queue()
        build = execute(claim_next())
        self.assertEqual(build.status, 'failed')
        self.assertIn('quota', build.reason)
