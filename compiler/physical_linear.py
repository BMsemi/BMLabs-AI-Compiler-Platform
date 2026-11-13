"""Physical X2 mapping and independent comparison against the compiled RTL oracle."""
import hashlib,json,uuid
from pathlib import Path
from django.conf import settings
from .supported_model import validate_ir
from .execution import write_json
from .physical_target import configuration,run as preflight


def prepare(work,config):
    ir=json.loads((work/'ir.json').read_text());model=validate_ir(ir)
    vectors=json.loads((work/'vectors.json').read_text())
    job={'schema':'bmlabs.zcu106-linear-job.v1','nonce':str(uuid.uuid4()),
        'tool_evidence_required':True,
        'input_sha256':hashlib.sha256((work/'ir.json').read_bytes()).hexdigest(),
        'expected_model':config['expected_model'],'asset_sha256':config['asset_sha256'],
        'weights':model['weights'],'bias':model['bias'],'relu':model['relu'],
        'inputs':[v['input'] for v in vectors]}
    write_json(work/'board_job.json',job)
    write_json(work/'physical_mapping.json',{'schema':'bmlabs.x2-overlay-mapping.v1',
        'input_rows':len(model['weights'][0]),'output_columns':len(model['weights']),
        'weight_layout':'Compiler output-major weights transposed to input-row/output-column int8 stream',
        'batch_limit':32,'mvm_placement':'ZCU106 PL axi_x2_mvm',
        'bias_relu_placement':'ZCU106 PS integer arithmetic','binding':'Pinned Qwen6 overlay/driver ABI; not final BM ASIC X2 ABI',
        'bitstream_role':'Existing base overlay, reprogrammed and then supplied compiled model weights',
        'generated_fabulous_configuration':False})
    return job,vectors


def validate_result(result,job,vectors):
    if result.get('schema')!='bmlabs.zcu106-linear-result.v1':
        raise ValueError('Unsupported physical result schema')
    if job.get('tool_evidence_required'):
        commands=result.get('tool_commands',[])
        if len(commands)!=2 or commands[0].get('argv')!=['gcc','--version'] or commands[1].get('argv',[])[:4]!=['gcc','-x','c','-shared']:
            raise ValueError('Missing board native compiler evidence')
        if any(c.get('exit_code')!=0 or not isinstance(c.get('seconds'),(int,float)) or c['seconds']<0 for c in commands):
            raise ValueError('Board native compiler did not complete successfully')
    if result.get('nonce')!=job['nonce'] or result.get('input_sha256')!=job['input_sha256']:
        raise ValueError('Stale or mismatched physical result identity')
    if result.get('physical_hardware') is not True or result.get('programming_executed') is not True or result.get('fpga_manager_state')!='operating':
        raise ValueError('Physical programming/execution was not confirmed')
    if result.get('accelerator_magic')!=0x58324d56 or type(result.get('accelerator_version'))!=int or result['accelerator_version']<0x20022:
        raise ValueError('Unsupported physical accelerator ABI')
    overlay='/home/xilinx/qwen6_20261005/fpga/qwen6/overlay/qwen6.bit'
    if result.get('bitstream_sha256')!=job['asset_sha256'][overlay]:raise ValueError('Physical bitstream mismatch')
    if len(result.get('raw_outputs',[]))!=len(vectors) or len(result.get('outputs',[]))!=len(vectors):
        raise ValueError('Physical result count mismatch')
    comparisons=0
    for i,vector in enumerate(vectors):
        for field in ('raw_outputs','outputs'):
            row=result[field][i]
            if not isinstance(row,list) or len(row)!=len(job['weights']) or any(type(v)!=int or not -(2**31)<=v<2**31 for v in row):
                raise ValueError('Invalid physical integer output shape or type')
        raw=[sum(x*w for x,w in zip(vector['input'],row)) for row in job['weights']]
        if result['raw_outputs'][i]!=raw:raise ValueError(f'Physical MVM mismatch at vector {i}')
        if result['outputs'][i]!=vector['expected']:raise ValueError(f'Physical model mismatch at vector {i}')
        comparisons+=len(raw)
    batches=result.get('batches',[])
    if len(batches)!=(len(vectors)+31)//32:raise ValueError('Missing physical batch evidence')
    for i,batch in enumerate(batches):
        count=min(32,len(vectors)-32*i);stats=batch.get('stats',{})
        if any(type(stats.get(key))!=int for key in ('error_code','cycles','tx_words')):
            raise ValueError('Invalid physical status types')
        if batch.get('start')!=32*i or batch.get('vectors')!=count or stats.get('error_code')!=0 or stats.get('cycles',0)<=0 or stats.get('tx_words')!=count*len(job['weights']):
            raise ValueError('Invalid physical transfer/cycle evidence')
    return {'status':'passed','physical_hardware':True,'programming_executed':True,
        'vectors':len(vectors),'outputs':len(job['weights']),'raw_mvm_comparisons':comparisons,'model_comparisons':comparisons,
        'bitstream_sha256':result['bitstream_sha256'],'accelerator_version':result['accelerator_version'],
        'scope':'Real PL MVM + PS bias/ReLU versus the independent RTL oracle. Existing Qwen6 overlay; no generated FABulous configuration.'}


def execute(work,command,config_hash):
    path,config=configuration()
    if config.get('programming_enabled') is not True:
        raise ValueError('Physical programming is disabled by the administrator.')
    preflight(work,command,config_hash)
    # Use exactly the immutable configuration that passed the queue-hash check.
    config=json.loads((work/'physical_target_configuration.json').read_text(encoding='utf-8'))
    job,vectors=prepare(work,config)
    command('zcu106_program_execute',[config['host_python'],'-I','-B',str(settings.BASE_DIR/'compiler/board_execute.py'),
        '--config',str(work/'physical_target_configuration.json'),'--work',str(work)],300)
    result=json.loads((work/'board_result.json').read_text())
    report=validate_result(result,job,vectors)
    write_json(work/'physical_verification.json',report)
    return report
