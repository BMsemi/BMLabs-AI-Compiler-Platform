"""Offline guardrail fixtures. These tests never constitute hardware evidence."""
import copy,hashlib,json,sys,tempfile
from pathlib import Path
from django.test import TestCase,SimpleTestCase,override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from accounts.models import User
from compiler.models import TargetProfile
from compiler.physical_target import ADAPTER
from compiler.physical_linear import validate_result,execute
from projects.models import Project
from projects.services import store_input
from builds.services import request_build

SOURCE=b"MODEL = {'schema':'bmlabs.linear-int8.v1','weights':[[127,-2]],'bias':[-7],'relu':False}"

@override_settings(COMPILER_ENABLED=True,COMPILER_MODEL_REPO='fixture',COMPILER_PYTHON=sys.executable)
class PhysicalQueueTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.config=self.root/'hardware.json'
        self.config.write_text(json.dumps({'adapter':ADAPTER,'host_python':sys.executable,'transport_source':__file__,'programming_enabled':True}))
        override=override_settings(MEDIA_ROOT=self.root,PHYSICAL_TARGET_CONFIG=str(self.config))
        override.enable();self.addCleanup(override.disable)
        self.user=User.objects.create_superuser('programmer@example.com',full_name='Test admin')
        self.target=TargetProfile.objects.create(name='Fixture',version='1',resources={'adapter':ADAPTER,'kind':'physical_board'})
        self.project=Project.objects.create(name='Fixture',owner=self.user,target=self.target)
        store_input(self.user,self.project,SimpleUploadedFile('model.py',SOURCE))

    def test_snapshots_input_and_config_and_excludes_parallel_board_job(self):
        job=request_build(self.user,self.project,'linear-fpga-v1')
        self.assertEqual(job.status,'queued')
        self.assertEqual(job.configuration['config_sha256'],hashlib.sha256(self.config.read_bytes()).hexdigest())
        with job.artifacts.get(name='input.py').file.open('rb') as f:self.assertEqual(f.read(),SOURCE)
        other=request_build(self.user,self.project,'zcu106-preflight-v1')
        self.assertEqual(other.status,'blocked')
        other=request_build(self.user,self.project,'linear-fpga-v1')
        self.assertEqual(other.status,'failed');self.assertIn('pending',other.reason)

    def test_non_admin_cannot_program(self):
        self.user.is_superuser=False;self.user.save()
        job=request_build(self.user,self.project,'linear-fpga-v1')
        self.assertEqual(job.status,'failed');self.assertIn('administrators',job.reason)
        self.assertFalse(job.stages.exists())

    def test_wrong_target_and_disabled_programming_fail_before_execution(self):
        self.project.target=None;self.project.save()
        self.assertEqual(request_build(self.user,self.project,'linear-fpga-v1').status,'failed')
        self.project.target=self.target;self.project.save()
        config=json.loads(self.config.read_text());config['programming_enabled']=False
        self.config.write_text(json.dumps(config))
        job=request_build(self.user,self.project,'linear-fpga-v1')
        self.assertEqual(job.status,'failed');self.assertIn('enabled',job.reason)
        with self.assertRaisesMessage(ValueError,'disabled'):
            execute(self.root,lambda *a:self.fail('Board must not be called'),hashlib.sha256(self.config.read_bytes()).hexdigest())


class PhysicalResultTests(SimpleTestCase):
    def setUp(self):
        self.job={'nonce':'fixture-nonce','input_sha256':'fixture-input','weights':[[2,-3]],
            'asset_sha256':{'/home/xilinx/qwen6_20261005/fpga/qwen6/overlay/qwen6.bit':'fixture-overlay'}}
        self.vectors=[{'input':[3,4],'expected':[0]}]
        self.result={'schema':'bmlabs.zcu106-linear-result.v1','nonce':'fixture-nonce','input_sha256':'fixture-input',
            'physical_hardware':True,'programming_executed':True,'fpga_manager_state':'operating',
            'accelerator_magic':0x58324d56,'accelerator_version':0x20025,'bitstream_sha256':'fixture-overlay',
            'raw_outputs':[[-6]],'outputs':[[0]],'batches':[{'start':0,'vectors':1,'stats':{'error_code':0,'cycles':10,'tx_words':1}}]}

    def test_accepts_complete_fixture_evidence(self):
        self.assertEqual(validate_result(self.result,self.job,self.vectors)['model_comparisons'],1)

    def test_rejects_stale_or_unprogrammed_or_wrong_overlay(self):
        for key,value in [('schema','other'),('nonce','stale'),('input_sha256','stale'),('bitstream_sha256','other'),
                          ('physical_hardware',False),('programming_executed',False),('fpga_manager_state','unknown'),('accelerator_version',0)]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_result({**self.result,key:value},self.job,self.vectors)

    def test_rejects_wrong_outputs_missing_vectors_or_coerced_numeric_types(self):
        for key,value in [('raw_outputs',[[6]]),('outputs',[[1]]),('outputs',[]),('outputs',[[False]]),('outputs',[[0.0]]),('raw_outputs',[[-6,0]])]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                validate_result({**self.result,key:value},self.job,self.vectors)

    def test_rejects_failed_or_missing_transfer_evidence(self):
        for key,value in [('error_code',2),('cycles',0),('tx_words',0),('cycles',True)]:
            result=copy.deepcopy(self.result);result['batches'][0]['stats'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_result(result,self.job,self.vectors)
        with self.assertRaises(ValueError):validate_result({**self.result,'batches':[]},self.job,self.vectors)

    def test_native_compiler_evidence_required_for_new_jobs(self):
        job={**self.job,'tool_evidence_required':True}
        with self.assertRaisesMessage(ValueError,'native compiler evidence'):
            validate_result(self.result,job,self.vectors)
        result={**self.result,'tool_commands':[{'argv':['gcc','--version'],'exit_code':0,'seconds':0.01},
                {'argv':['gcc','-x','c','-shared'],'exit_code':0,'seconds':0.02}]}
        validate_result(result,job,self.vectors)
        result['tool_commands'][1]['exit_code']=1
        with self.assertRaisesMessage(ValueError,'did not complete'):
            validate_result(result,job,self.vectors)
