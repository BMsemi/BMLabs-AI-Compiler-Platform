import hashlib,json,sys,tempfile
from pathlib import Path
from django.test import TestCase,override_settings
from accounts.models import User
from projects.models import Project
from compiler.models import TargetProfile
from compiler.board_probe import validate_report
from compiler.physical_target import ADAPTER,run
from builds.services import request_build
from builds.models import BuildJob


@override_settings(COMPILER_ENABLED=True,SECURE_SSL_REDIRECT=False)
class PhysicalTargetTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.config=self.root/'physical.json'
        self.config.write_text(json.dumps({'adapter':ADAPTER,'host_python':sys.executable,'transport_source':__file__}))
        override=override_settings(PHYSICAL_TARGET_CONFIG=str(self.config))
        override.enable();self.addCleanup(override.disable)
        self.user=User.objects.create_superuser('board-admin@example.com',full_name='Board admin')
        self.target=TargetProfile.objects.create(name='Test physical board',version='fixture',resources={'adapter':ADAPTER,'kind':'physical_board'})
        self.project=Project.objects.create(name='Test board project',owner=self.user,target=self.target)

    def test_queues_read_only_check_with_configuration_hash(self):
        job=request_build(self.user,self.project,pipeline='zcu106-preflight-v1')
        self.assertEqual(job.status,'queued')
        self.assertEqual(job.configuration['config_sha256'],hashlib.sha256(self.config.read_bytes()).hexdigest())
        duplicate=request_build(self.user,self.project,pipeline='zcu106-preflight-v1')
        self.assertEqual(duplicate.status,'blocked')
        self.assertIn('already pending',duplicate.reason)

    def test_non_admin_cannot_access_physical_board(self):
        self.user.is_superuser=False;self.user.save()
        job=request_build(self.user,self.project,pipeline='zcu106-preflight-v1')
        self.assertEqual(job.status,'blocked')
        self.assertIn('administrators',job.reason)

    def test_wrong_target_and_missing_configuration_block(self):
        self.project.target=None;self.project.save()
        job=request_build(self.user,self.project,pipeline='zcu106-preflight-v1')
        self.assertEqual(job.status,'blocked')
        self.project.target=self.target;self.project.save()
        self.config.unlink()
        job=request_build(self.user,self.project,pipeline='zcu106-preflight-v1')
        self.assertEqual(job.status,'blocked')

    def test_hardware_identity_and_overlay_integrity_are_required(self):
        config={'expected_model':'ZynqMP ZCU106 RevA','asset_sha256':{'/test/overlay.bit':'abc'}}
        report={'model':config['expected_model'],'architecture':'aarch64','pynq':'test-fixture','assets':{'/test/overlay.bit':{'exists':True,'sha256':'abc'}}}
        validate_report(report,config)
        with self.assertRaises(ValueError):validate_report({**report,'model':'unrelated board'},config)
        with self.assertRaises(ValueError):validate_report({**report,'assets':{}},config)
        with self.assertRaises(ValueError):validate_report({**report,'architecture':'x86_64'},config)

    def test_configuration_drift_prevents_board_access(self):
        def unexpected(*args):self.fail('No board command may execute after configuration drift')
        with self.assertRaisesMessage(ValueError,'changed since queueing'):
            run(self.root,unexpected,'wrong-hash')
