import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase, SimpleTestCase, override_settings
from accounts.models import User
from projects.models import Project
from compiler.models import TargetProfile
from compiler.sky130_runtime import run, PIPELINE
from compiler.sky130_user_design import REVISION
from builds.services import request_build


@override_settings(COMPILER_ENABLED=True)
class QueueTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'profile.json'
        self.profile={'schema':'bmlabs.sky130-toolchain.v1','revision':REVISION}
        self.path.write_text(json.dumps(self.profile))
        self.admin=User.objects.create_superuser('sky130@example.com',full_name='Admin')
        self.target=TargetProfile.objects.create(name='Existing physical board',version='1')
        self.project=Project.objects.create(name='Test',owner=self.admin,target=self.target)

    def test_queue_has_separate_target_scope_and_immutable_profile_hash(self):
        with patch('compiler.sky130_runtime.configuration',return_value=(self.path,self.profile)):
            job=request_build(self.admin,self.project,PIPELINE)
            duplicate=request_build(self.admin,self.project,PIPELINE)
        self.assertEqual(job.status,'queued')
        self.assertIsNone(job.target)
        self.assertEqual(job.configuration['profile_sha256'],hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(job.input_manifest,[])
        self.assertEqual(duplicate.status,'blocked')
        self.project.refresh_from_db()
        self.assertEqual(self.project.target,self.target)

    def test_missing_configuration_blocks_without_success(self):
        with patch('compiler.sky130_runtime.configuration',side_effect=FileNotFoundError('Missing toolchain profile')):
            job=request_build(self.admin,self.project,PIPELINE)
        self.assertEqual(job.status,'blocked')
        self.assertIn('Missing toolchain',job.reason)

    def test_non_admin_cannot_launch_qualification(self):
        self.admin.is_superuser=False
        self.admin.save()
        job=request_build(self.admin,self.project,PIPELINE)
        self.assertEqual(job.status,'blocked')


class RuntimeTests(SimpleTestCase):
    def test_changed_profile_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'profile.json'
            path.write_text('{}')
            with patch('compiler.sky130_runtime.configuration',return_value=(path,{})), patch('compiler.sky130_runtime.wsl_path'):
                with self.assertRaisesRegex(ValueError,'changed after queueing'):
                    run(Path(tmp),lambda *a: self.fail('Must not execute'), 'wrong_hash')

    def test_failed_process_preserves_partial_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp)
            profile={'distro':'fixture','user':'fixture','repository':'/fixture','tool_path':'/fixture/bin'}
            path=work/'profile.json';path.write_text(json.dumps(profile))
            def fail(*args):
                output=work/'sky130-output';output.mkdir()
                (output/'synth.stderr.log').write_text('real tool error fixture')
                raise RuntimeError('exit 2')
            with patch('compiler.sky130_runtime.configuration',return_value=(path,profile)), patch('compiler.sky130_runtime.wsl_path',side_effect=str):
                with self.assertRaisesRegex(RuntimeError,'exit 2'):
                    run(work,fail,hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual((work/'sky130_synth.stderr.log').read_text(),'real tool error fixture')
