"""Administrator-installed physical target configuration; user input is never a command."""
import hashlib
import json
from pathlib import Path
from django.conf import settings

ADAPTER='zcu106-qwen6-fixed-overlay-v1'


def configuration():
    path=Path(settings.PHYSICAL_TARGET_CONFIG)
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('adapter')!=ADAPTER:
        raise ValueError('Unsupported physical target adapter.')
    for key in ('host_python','transport_source'):
        if not Path(data[key]).is_file():raise ValueError('Missing physical target dependency: '+key)
    return path,data


def summary():
    try:
        path,data=configuration()
        return {'configured':True,'adapter':ADAPTER,'board':'ZCU106',
            'transport':data['serial']['port'],'baud':data['serial']['baud'],
            'scope':'Pinned Qwen6 overlay; PL int8 MVM and PS bias/ReLU',
            'programming_enabled':data.get('programming_enabled') is True,
            'pipeline':'linear-fpga-v1',
            'availability_note':'Configuration only; each build probes the connected board and records its own hardware result.',
            'accepts_generated_fabulous_bitstream':False}
    except (OSError,ValueError,KeyError) as exc:
        return {'configured':False,'detail':str(exc),'physical_test_executed':False}


def run(work,command,expected_hash):
    path,data=configuration()
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected_hash:
        raise ValueError('Physical target configuration changed since queueing. Request a new check.')
    snapshot=work/'physical_target_configuration.json'
    snapshot.write_bytes(path.read_bytes())
    command('zcu106_board_preflight',[data['host_python'],'-I','-B',str(settings.BASE_DIR/'compiler/board_probe.py'),
        '--config',str(snapshot),'--out',str(work/'physical_target_preflight.json')],90)
    report=json.loads((work/'physical_target_preflight.json').read_text())
    if report.get('status')!='passed' or report.get('physical_test_executed') is not False:
        raise ValueError('Board preflight did not produce a valid read-only verification report.')
    return report
