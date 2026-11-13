"""Execute compiled int8 weights on the pinned ZCU106 X2 accelerator.

Runs on the board as root through the existing PYNQ DMA-heap backend. There is
no software MVM fallback. Bias and ReLU currently run on the processing system.
"""
import argparse
from dataclasses import asdict
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import subprocess
from types import SimpleNamespace


def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


def run(job,out):
    import numpy as np
    if job.get('schema')!='bmlabs.zcu106-linear-job.v1':raise ValueError('Unsupported board job')
    inputs=job['inputs'];weights=job['weights'];bias=job['bias']
    if not 1<=len(weights)<=32 or not 1<=len(weights[0])<=32 or not 1<=len(inputs)<=512:
        raise ValueError('Unsupported model or vector count')
    rows=len(weights[0]);cols=len(weights)
    if any(len(row)!=rows or any(type(v)!=int or not -127<=v<=127 for v in row) for row in weights):raise ValueError('Invalid weights')
    if any(len(row)!=rows or any(type(v)!=int or not -128<=v<=127 for v in row) for row in inputs):raise ValueError('Invalid input vectors')
    if len(bias)!=cols or any(type(v)!=int or abs(v)>1048576 for v in bias) or type(job['relu'])!=bool:raise ValueError('Invalid bias/ReLU')
    if Path('/proc/device-tree/model').read_bytes().decode().rstrip('\x00')!=job['expected_model']:raise ValueError('Board identity mismatch')
    import os
    for process in Path('/proc').iterdir():
        if not process.name.isdigit() or int(process.name)==os.getpid():continue
        try:args=(process/'cmdline').read_bytes().decode(errors='replace').split('\x00')
        except OSError:continue
        if args and 'python' in Path(args[0]).name and any(
                '/neuromorphic_platform/runner.py' in arg or Path(arg).name in ('board_smoke.py','board_linear_runner.py')
                or arg=='fpga6' for arg in args[1:]):
            raise RuntimeError('Another FPGA job appears active (PID '+process.name+'); refusing to replace its overlay')
    for path,digest in job['asset_sha256'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:raise ValueError('Board asset changed: '+path)
    root=Path('/home/xilinx/qwen6_20261005/fpga/qwen6')
    overlay_path=root/'overlay/qwen6.bit'
    # Pin every imported transport/driver and firmware input before programming.
    for path in [root/'board_dma_heap.py',root/'axi_x2_mvm_driver.py',overlay_path,overlay_path.with_suffix('.hwh')]:
        if str(path) not in job['asset_sha256']:raise ValueError('Missing required asset pin: '+str(path))
    lock=open('/var/lock/bmlabs-fpga.lock','a+')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        tool_commands=[]
        def recorded_tool(argv,**kwargs):
            checked=kwargs.pop('check',False)
            began=time.monotonic()
            try:
                completed=subprocess.run(argv,**kwargs,capture_output=True,timeout=30,check=False)
            except (OSError,subprocess.SubprocessError) as exc:
                tool_commands.append({'argv':argv,'exit_code':None,'error':str(exc),
                    'seconds':round(time.monotonic()-began,4),
                    'stdout':(getattr(exc,'stdout',None) or b'').decode(errors='replace'),
                    'stderr':(getattr(exc,'stderr',None) or b'').decode(errors='replace')})
                Path(out).with_name('tool_commands.json').write_text(json.dumps(tool_commands,indent=2))
                raise
            tool_commands.append({'argv':argv,'exit_code':completed.returncode,
                'stdout':completed.stdout.decode(errors='replace'),'stderr':completed.stderr.decode(errors='replace'),
                'seconds':round(time.monotonic()-began,4),
                'stdin_sha256':hashlib.sha256(kwargs.get('input',b'')).hexdigest()})
            Path(out).with_name('tool_commands.json').write_text(json.dumps(tool_commands,indent=2))
            if checked:completed.check_returncode()
            return completed
        recorded_tool(['gcc','--version'],check=True)
        heap=load_module('bmlabs_dma_heap',root/'board_dma_heap.py')
        # Instrument only this pinned module; do not alter the repository source
        # or subprocess behavior used by PYNQ and other imported modules.
        heap.subprocess=SimpleNamespace(run=recorded_tool)
        heap.install()
        driver=load_module('bmlabs_x2_driver',root/'axi_x2_mvm_driver.py')
        from pynq import Overlay
        overlay=Overlay(str(overlay_path),download=False)
        if 'axi_x2_mvm' not in overlay.ip_dict:raise ValueError('Pinned overlay has no X2 MVM IP')
        began=time.monotonic();overlay.download()
        if Path('/sys/class/fpga_manager/fpga0/state').read_text().strip()!='operating':raise RuntimeError('FPGA programming did not finish')
        accelerator=driver.AxiX2MvmPynq(overlay=overlay,accel_name='axi_x2_mvm',timeout_s=10)
        raw=[];batches=[]
        matrix=np.asarray(weights,dtype=np.int8).T.copy()
        for start in range(0,len(inputs),32):
            vectors=np.asarray(inputs[start:start+32],dtype=np.int8)
            actual=accelerator.run_mvm_batch(vectors,matrix)
            raw.extend(actual.tolist())
            stats=asdict(accelerator.stats())
            if stats['error_code'] or stats['cycles']<=0:raise RuntimeError('Invalid physical accelerator status')
            batches.append({'start':start,'vectors':len(vectors),'stats':stats})
        # This postprocessing placement is explicit in the result and manifest.
        result=[]
        for row in raw:
            values=[v+b for v,b in zip(row,bias)]
            if any(not -(2**31)<=v<2**31 for v in values):raise ValueError('Accumulator overflow')
            result.append([max(0,v) for v in values] if job['relu'] else values)
        report={'schema':'bmlabs.zcu106-linear-result.v1','nonce':job['nonce'],'input_sha256':job['input_sha256'],
            'physical_hardware':True,'programming_executed':True,'fpga_manager_state':'operating',
            'model_execution':'PL signed-int8 MVM; PS integer bias and ReLU',
            'bitstream':str(overlay_path),'bitstream_sha256':job['asset_sha256'][str(overlay_path)],
            'new_bitstream_generated':False,'accelerator_magic':driver.MAGIC_X2MV,'accelerator_version':accelerator.version,
            'raw_outputs':raw,'outputs':result,'batches':batches,'seconds':round(time.monotonic()-began,4)}
        report['tool_commands']=tool_commands
        report['numpy_version']=np.__version__
        report['dma_library_sha256']=hashlib.sha256((root/'dma_barrier.so').read_bytes()).hexdigest()
        Path(out).write_text(json.dumps(report,indent=2))
        print('BMLABS_PHYSICAL_LINEAR_EXECUTED vectors='+str(len(inputs)),flush=True)
    finally:
        lock.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--job',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    try:run(json.loads(Path(a.job).read_text()),a.out)
    except Exception as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr);sys.exit(1)
