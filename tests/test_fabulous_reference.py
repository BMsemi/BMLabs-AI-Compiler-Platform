"""Fixtures exercise failure gates only; real acceptance builds are separate."""
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase, override_settings
from compiler.fabulous_reference import MARKER, validate_simulation, verify_hex, required_files
from compiler.fabulous_runtime import command, path_for_runtime
from compiler.hardware import fabulous_preflight
from accounts.models import User
from projects.models import Project
from compiler.models import TargetProfile
from builds.services import request_build


class ReferenceEvidenceTests(SimpleTestCase):
    def output(self):
        return '\n'.join([f'fabric(I_top) = 0x{i:x} gold = 0x{i:x}, fabric(T_top) = 0xffffffe gold = 0xffffffe' for i in range(100)]+[MARKER])

    def test_requires_completion_and_full_comparisons(self):
        for output in ['', 'Simulation finished', MARKER, self.output().replace(MARKER, '')]:
            with self.subTest(output=output[:40]), self.assertRaises(ValueError):
                validate_simulation(output)
        self.assertEqual(validate_simulation(self.output())['comparisons'], 100)

    def test_rejects_mismatch_unknown_or_constant_outputs(self):
        for output in [self.output().replace('0x1 gold', '0x2 gold', 1),
                       self.output().replace('0x1 gold', '0xxx gold', 1),
                       self.output().replace('0x1 gold = 0x1', '0x0 gold = 0x0', 1)]:
            with self.assertRaises(ValueError):
                validate_simulation(output)

    def test_shifted_counter_cannot_pass_even_when_golden_matches(self):
        output='\n'.join([f'fabric(I_top) = 0x{i:x} gold = 0x{i:x}, fabric(T_top) = 0xffffffe gold = 0xffffffe' for i in range(1,101)]+[MARKER])
        with self.assertRaisesRegex(ValueError,'reset/count sequence'):
            validate_simulation(output)

    def test_exact_binary_must_be_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); binary=root/'test.bin'; hexfile=root/'test.hex'
            binary.write_bytes(b'\x01\x02\x03\x04')
            hexfile.write_text('01 02 03 04 '+'00 '*16380)
            self.assertEqual(verify_hex(binary,hexfile)['bytes'],4)
            for data in ['00 '*16384, '01 02 03 04', '01 02 03 04 '+'00 '*16379+'ff']:
                hexfile.write_text(data)
                with self.assertRaises(ValueError): verify_hex(binary,hexfile)

    def test_empty_or_absent_output_never_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for present in [False, True]:
                if present: (root/'out.bin').touch()
                with self.assertRaises(ValueError): required_files(root,['out.bin'])

    @override_settings(FABULOUS_RUNTIME={})
    def test_missing_runtime_is_explicit(self):
        with self.assertRaisesRegex(ValueError,'not configured'): command('FABulous')

    @override_settings(FABULOUS_RUNTIME={'distro':'test-distro','venv':'/opt/fab','cad_bin':'/opt/cad','user':'bmlabs'})
    def test_runtime_uses_explicit_user_clean_environment_and_timeout(self):
        argv=command('FABulous',['--version'],timeout=17)
        self.assertIn('bmlabs',argv); self.assertIn('17',argv); self.assertIn('-i',argv)
        self.assertEqual(argv[-2:],['/opt/fab/bin/FABulous','--version'])
        self.assertEqual(path_for_runtime(Path('//wsl.localhost/test-distro/home/bmlabs/work/builds')), '/home/bmlabs/work/builds')

    @patch('compiler.inventory.current', return_value={'fabulous_tools_ready': True, 'tools': {k:{'successful':True} for k in ['fabulous','fabulous_yosys','fabulous_nextpnr']}})
    def test_reference_tools_do_not_validate_bm_target(self, _):
        result=fabulous_preflight()
        self.assertTrue(result['tools_ready']); self.assertFalse(result['executed'])
        self.assertEqual(result['status'],'unsupported')
        self.assertIn('Validated BM FABulous target profile',result['missing'])


@override_settings(COMPILER_ENABLED=True,FABULOUS_RUNTIME={'distro':'test'},FABULOUS_WORK_ROOT='C:/test')
class ReferenceQueueTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('reference@example.com','Test-password-8712!',email_verified=True)
        self.target=TargetProfile.objects.create(name='BM candidate',version='draft')
        self.project=Project.objects.create(name='Test reference',owner=self.user,target=self.target)

    def test_reference_build_does_not_claim_selected_bm_target(self):
        job=request_build(self.user,self.project,'fabulous-reference-v1')
        self.assertEqual(job.status,'queued'); self.assertIsNone(job.target)
        self.assertEqual(job.target_snapshot['status'],'reference')
        self.assertEqual(job.x2_snapshot,{})
        self.assertFalse(job.artifacts.exists())

    def test_queue_limit_also_applies_to_reference(self):
        for _ in range(5): self.assertEqual(request_build(self.user,self.project,'fabulous-reference-v1').status,'queued')
        self.assertEqual(request_build(self.user,self.project,'fabulous-reference-v1').status,'blocked')

    def test_interrupted_reference_archives_partial_linux_work(self):
        from builds.runner import claim_next, recover_interrupted
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=Path(directory)):
            job=request_build(self.user,self.project,'fabulous-reference-v1'); claim_next()
            work=Path(directory)/'work'/str(job.pk); work.mkdir(parents=True)
            with patch('compiler.fabulous_reference.archive_project') as archive:
                recover_interrupted()
                archive.assert_called_once_with(Path('C:/test')/str(job.pk),work)
            job.refresh_from_db()
            self.assertEqual(job.status,'failed')
