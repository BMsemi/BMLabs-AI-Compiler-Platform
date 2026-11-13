"""Bounded serial transfer and execution of a fixed, reviewed board adapter."""
import argparse,base64,hashlib,importlib.util,json,re,shlex,sys,time,uuid
from pathlib import Path


def run(config,work,job):
    transport=Path(config['transport_source'])
    if hashlib.sha256(transport.read_bytes()).hexdigest()!=config['transport_sha256']:raise ValueError('Transport changed')
    spec=importlib.util.spec_from_file_location('bmlabs_transport',transport);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    remote='/home/xilinx/neuromorphic_jobs/bmlabs_'+uuid.UUID(job['nonce']).hex
    source=Path(__file__).with_name('board_linear_runner.py').read_bytes()
    encoded=json.dumps(job,separators=(',',':')).encode()
    evidence={'remote_directory':remote,'runner_sha256':hashlib.sha256(source).hexdigest(),'job_sha256':hashlib.sha256(encoded).hexdigest(),'commands':[]}
    start=time.monotonic()
    def command(console,text,timeout=30):
        began=time.monotonic()
        try:
            value=console.command(text,timeout=timeout)
            evidence['commands'].append({'command':text,'exit_code':0,'seconds':round(time.monotonic()-began,4),'stdout':value})
            return value
        except Exception as exc:
            evidence['commands'].append({'command':text,'exit_code':None,'seconds':round(time.monotonic()-began,4),'error':str(exc)})
            raise
    def retrieve(console,name):
        text='import base64;print("BMLABS_FILE:"+base64.b64encode(open('+repr(remote+'/'+name)+',"rb").read()).decode())'
        raw=command(console,'python3 -c '+shlex.quote(text),45)
        return base64.b64decode(raw.split('BMLABS_FILE:',1)[1].splitlines()[0],validate=True)
    try:
        with module.SerialConsole(config['serial']) as console:
            command(console,'mkdir -p '+shlex.quote(remote))
            console.upload(encoded,remote+'/job.json');console.upload(source,remote+'/runner.py')
            verify='import hashlib;assert hashlib.sha256(open('+repr(remote+'/runner.py')+',"rb").read()).hexdigest()=='+repr(evidence['runner_sha256'])+';assert hashlib.sha256(open('+repr(remote+'/job.json')+',"rb").read()).hexdigest()=='+repr(evidence['job_sha256'])
            command(console,'python3 -c '+shlex.quote(verify))
            argv=['sudo','-n',config['board_python'],remote+'/runner.py','--job',remote+'/job.json','--out',remote+'/result.json']
            text=' '.join(map(shlex.quote,argv))+' > '+remote+'/stdout.log 2> '+remote+'/stderr.log; rc=$?; printf "BMLABS_REMOTE_EXIT:%s\\n" "$rc"'
            raw=command(console,text,180)
            matches=re.findall(r'BMLABS_REMOTE_EXIT:(\d+)',raw)
            if len(matches)!=1:raise ValueError('Missing remote exit code')
            evidence['remote_argv']=argv;evidence['remote_exit_code']=int(matches[0])
            for name in ['stdout.log','stderr.log']:
                (work/('board_'+name)).write_bytes(retrieve(console,name))
            # Retain internal GCC evidence even if a later board operation fails.
            exists=command(console,'test -f '+remote+'/tool_commands.json && printf BMLABS_TOOLS_PRESENT || true')
            if 'BMLABS_TOOLS_PRESENT' in exists:
                (work/'board_tool_commands.json').write_bytes(retrieve(console,'tool_commands.json'))
            if evidence['remote_exit_code']!=0:raise RuntimeError('Physical board execution failed; see board_stderr.log')
            data=retrieve(console,'result.json');(work/'board_result.json').write_bytes(data)
            return json.loads(data)
    finally:
        evidence['seconds']=round(time.monotonic()-start,4)
        (work/'board_transport.json').write_text(json.dumps(evidence,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--work',required=True)
    args=parser.parse_args();work=Path(args.work)
    try:
        result=run(json.loads(Path(args.config).read_text()),work,json.loads((work/'board_job.json').read_text()))
        print('BMLABS_BOARD_EXECUTION_COMPLETE nonce='+result['nonce'])
    except Exception as exc:print(type(exc).__name__+': '+str(exc),file=sys.stderr);sys.exit(1)
