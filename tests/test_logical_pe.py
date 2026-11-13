import json
import gzip
import hashlib
from pathlib import Path
import tempfile
from django.conf import settings
from django.test import SimpleTestCase, override_settings
from compiler.execution import run_command
from compiler.hardware import prototype_scope
from compiler.artifact_packaging import compress_diagnostics


class DiagnosticPackagingTests(SimpleTestCase):
    def test_round_trip_hash_and_original_rtl_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = b'generated netlist evidence\n' * 100
            (root/'synthesized.json').write_bytes(data)
            (root/'model.v').write_bytes(data)
            report = compress_diagnostics(root, threshold=20)
            self.assertEqual(gzip.decompress((root/'synthesized.json.gz').read_bytes()), data)
            self.assertEqual(report['synthesized.json']['uncompressed_sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual((root/'model.v').read_bytes(), data)
            self.assertFalse((root/'synthesized.json').exists())

    def test_existing_archive_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'netlist.vvp').write_bytes(b'new')
            (root/'netlist.vvp.gz').write_bytes(b'existing')
            with self.assertRaises(ValueError):
                compress_diagnostics(root, threshold=1)
            self.assertEqual((root/'netlist.vvp').read_bytes(), b'new')


class LogicalPETests(SimpleTestCase):
    def run_pe(self, weights, bias, relu, vectors):
        if not Path(settings.COMPILER_MODEL_REPO, 'bm_models/vendor/neuromorphic_x1/neuromorphic_x2.py').is_file():
            self.skipTest('Configured upstream PE repository unavailable; integration test requires its real simulator.')
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            ir = {'schema': 'bmlabs.linear-int8.v1', 'input_dtype': 'int8', 'output_dtype': 'int32',
                  'weights': weights, 'bias': bias, 'relu': relu}
            (out/'ir.json').write_text(json.dumps(ir))
            (out/'vectors.json').write_text(json.dumps(vectors))
            result = run_command([settings.COMPILER_PYTHON, '-I', '-B', str(settings.BASE_DIR/'compiler/logical_pe.py'),
                '--repo', settings.COMPILER_MODEL_REPO, '--ir', str(out/'ir.json'),
                '--vectors', str(out/'vectors.json'), '--out', str(out)], out, 30)
            files = {p.name: json.loads(p.read_text()) for p in out.glob('logical_pe*.json')}
            return result, files

    def test_non_square_orientation_padding_and_accumulator_bias(self):
        result, files = self.run_pe([[1, -2, 3], [-4, 5, 6]], [7, -8], False,
            [{'input': [2, -3, 4], 'expected': [27, -7]},
             {'input': [-128, 127, 0], 'expected': [-375, 1139]}])
        self.assertTrue(result['successful'], result)
        self.assertEqual(files['logical_pe_mapping.json']['weights_input_rows_output_columns'][0][:2], [1, -4])
        report = files['logical_pe_verification.json']
        self.assertFalse(report['physical_hardware'])
        self.assertEqual(report['stage_cycles']['PROGRAM'], 51200)
        self.assertEqual(report['stage_cycles']['COMPUTE'], 576)
        self.assertEqual(report['comparisons'], 4)

    def test_full_array_extrema_and_relu(self):
        result, files = self.run_pe([[127] * 32, [-127] * 32] + [[0] * 32 for _ in range(30)],
            [0] * 32, True, [{'input': [-128] * 32, 'expected': [0, 520192] + [0] * 30}])
        self.assertTrue(result['successful'], result)
        self.assertEqual(files['logical_pe_verification.json']['comparisons'], 32)

    def test_numerical_mismatch_is_nonzero_without_pass_report(self):
        result, files = self.run_pe([[1]], [0], False, [{'input': [1], 'expected': [2]}])
        self.assertFalse(result['successful'])
        self.assertNotEqual(result['exit_code'], 0)
        self.assertIn('numerical mismatch', result['stderr'])
        self.assertNotIn('logical_pe_verification.json', files)
        self.assertEqual(files['logical_pe_results.json'][0]['actual'], [1])

    def test_empty_vectors_cannot_pass(self):
        result, files = self.run_pe([[1]], [0], False, [])
        self.assertFalse(result['successful'])
        self.assertNotIn('logical_pe_verification.json', files)

    @override_settings(COMPILER_MODEL_REPO='missing-test-repository')
    def test_scope_keeps_board_and_fabric_separate(self):
        scope = prototype_scope()
        self.assertIsNone(scope['logical_pe']['physical_fabric_dimensions'])
        self.assertFalse(scope['zcu106_self_test']['source_available'])
        self.assertFalse(scope['zcu106_self_test']['executed'])
        self.assertFalse(scope['zcu106_self_test']['accepts_generated_fabulous_bitstream'])
        self.assertIn('Logical 32x32 PE simulation', scope['physical_integration']['does_not_block'])
