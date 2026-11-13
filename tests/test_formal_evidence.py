import json,tempfile
from pathlib import Path
from django.test import SimpleTestCase,override_settings
from compiler.synthesis import verify_equivalence

@override_settings(TOOLCHAIN={'YOSYS_PATH':'C:/test-tools/yosys.exe'})
class FormalEvidenceTests(SimpleTestCase):
    # Deliberate fixtures test the evidence gate; these are never compiler artifacts.
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.work=Path(self.temp.name)
        ports={'x0':{'direction':'input','bits':[2]},'y0':{'direction':'output','bits':[3]}}
        for name in ['model','synthesized']:
            (self.work/(name+'_interface.json')).write_text(json.dumps({'modules':{'linear_model':{'ports':ports}}}))
            (self.work/(name+'.aig')).write_bytes(b'aig 2 1 0 1 1\n')

    def test_zero_exit_without_positive_proof_is_rejected(self):
        for output in ['', 'Networks are NOT EQUIVALENT.', 'Unknown command: cec']:
            with self.subTest(output=output),self.assertRaisesRegex(ValueError,'did not prove'):
                verify_equivalence(self.work,lambda *args: {'stdout':output,'exit_code':0})

    def test_changed_port_names_rejected_before_proof(self):
        p=self.work/'synthesized_interface.json';d=json.loads(p.read_text())
        ports=d['modules']['linear_model']['ports'];ports['other']=ports.pop('x0');p.write_text(json.dumps(d))
        calls=[]
        with self.assertRaisesRegex(ValueError,'port declarations differ'):
            verify_equivalence(self.work,lambda name,*args: calls.append(name))
        self.assertNotIn('abc_equivalence',calls)

    def test_unexpected_state_is_rejected(self):
        (self.work/'synthesized.aig').write_bytes(b'aig 2 1 1 1 1\n')
        with self.assertRaisesRegex(ValueError,'unexpected sequential state'):
            verify_equivalence(self.work,lambda *args: None)
