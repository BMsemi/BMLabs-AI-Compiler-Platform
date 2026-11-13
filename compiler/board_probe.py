"""Read-only ZCU106 identity, runtime and fixed-overlay integrity check.

This never programs an FPGA or invokes the numerical self-test runner.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

REMOTE = '''import hashlib,json,platform,sys
from pathlib import Path
import pynq
import xml.etree.ElementTree as ET
paths=ASSET_PATHS
assets={}
for name in paths:
 p=Path(name)
 assets[name]={'exists':p.is_file(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None}
model=Path('/proc/device-tree/model').read_bytes().decode().rstrip('\\x00')
hwh=next((p for p in paths if p.endswith('.hwh')),None)
clocks=[]
if hwh and Path(hwh).is_file():
 root=ET.parse(hwh).getroot()
 for module in root.iter('MODULE'):
  for param in module.findall('./PARAMETERS/PARAMETER'):
   if param.get('NAME') in ('PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ','C_S_AXI_ACLK_FREQ_HZ','C_M_AXI_ACLK_FREQ_HZ'):
    clocks.append({'module':module.get('INSTANCE'),'parameter':param.get('NAME'),'value':param.get('VALUE')})
print('BMLABS_BOARD_REPORT:'+json.dumps({'model':model,'hostname':platform.node(),'architecture':platform.machine(),'python':sys.version,'pynq':pynq.__version__,'assets':assets,'clocks':clocks}))
'''


def validate_report(report, config):
    if report.get('model') != config['expected_model']:
        raise ValueError('Physical board identity does not match the configured target.')
    if report.get('architecture') != 'aarch64' or not report.get('pynq'):
        raise ValueError('Required ARM64/PYNQ board runtime is missing.')
    for path, digest in config['asset_sha256'].items():
        actual = report.get('assets', {}).get(path, {})
        if actual.get('exists') is not True or actual.get('sha256') != digest:
            raise ValueError('Missing or changed board asset: '+path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    report={'status':'failed','checked_at':datetime.now(timezone.utc).isoformat(),
        'scope':'Read-only board identity, runtime and installed fixed-overlay integrity',
        'physical_test_executed':False,'programming_executed':False,'accepts_generated_fabulous_bitstream':False}
    try:
        config=json.loads(Path(args.config).read_text())
        transport=Path(config['transport_source'])
        if hashlib.sha256(transport.read_bytes()).hexdigest()!=config['transport_sha256']:
            raise ValueError('Serial transport source changed; review and re-pin it before board access.')
        spec=importlib.util.spec_from_file_location('bmlabs_board_transport',transport)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        source=REMOTE.replace('ASSET_PATHS',repr(list(config['asset_sha256'])))
        payload=base64.b64encode(source.encode()).decode()
        command=shlex.quote(config['board_python'])+' -c '+shlex.quote('import base64;exec(base64.b64decode('+repr(payload)+'))')
        report['remote_command']=command
        with module.SerialConsole(config['serial']) as console:
            raw=console.command(command,timeout=45)
        report['remote_exit_code']=0
        report['remote_stdout']=raw
        marker='BMLABS_BOARD_REPORT:'
        lines=[line for line in raw.splitlines() if marker in line]
        if len(lines)!=1:raise ValueError('Board response missing its unique report marker.')
        board=json.loads(lines[0].split(marker,1)[1])
        validate_report(board,config)
        report.update(board);report['status']='passed'
    except Exception as exc:
        report['error']=str(exc)
    Path(args.out).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':sys.exit(main())
