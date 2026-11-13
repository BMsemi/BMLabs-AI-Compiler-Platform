"""Run pinned, administrator-owned SKY130 ReRAM example Makefiles in Linux.

These outputs configure classic_fabric_reram; they are NOT Xilinx bitstreams.
This command does not execute uploaded Makefiles or program physical hardware.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import tempfile

from compiler.execution import run_command, write_json

REVISION = 'e0790eb11a1e95914f2beb8f175396a0924144ed'
PRIMITIVES_REVISION = '0651993fdbd40d464a5f683881ba1e5c0db7b453'
DESIGNS = ('counter', 'reram_cim_32x32')


def validate_configuration(bit, hex_text):
    """Validate the pinned fabric's complete frame stream, without unpickling input."""
    # The pinned generated RTL exposes 20 * 32 data bits and 21 * 20 strobes.
    prefix=bytes.fromhex('00AAFF01000000010000000000000000FAB0FAB1')
    if len(bit) != len(prefix)+21*20*(4+20*4)+4 or not bit.startswith(prefix):
        raise ValueError('Wrong configuration length or synchronization header')
    offset=len(prefix)
    for column in range(21):
        for frame in range(20):
            header=int.from_bytes(bit[offset:offset+4],'big')
            if header != (column<<27)|(1<<frame):
                raise ValueError(f'Invalid frame header at column {column}, frame {frame}')
            offset+=84
    if bit[offset:] != bytes.fromhex('00100000'):
        raise ValueError('Missing configuration desynchronization word')
    if bytes.fromhex(hex_text) != bit:
        raise ValueError('Hex export does not match binary configuration')
    return {'status':'passed','columns':21,'rows':20,'frames_per_column':20,
            'frame_words':8400,'bytes':len(bit),'hex_matches_binary':True,
            'scope':'File framing only; no hardware loading or functional verification'}


def build(repo, output, design, tool_path):
    repo, output = Path(repo).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = dict(schema='bmlabs.sky130-user-design.v1', status='running',
                  target='classic_fabric_reram', design=design, commands=[], artifacts=[],
                  timing_closed=False, hardware_verified=False,
                  configuration_format='FABulous SKY130 fabric configuration; not Xilinx .bit')
    work = None
    def save():
        write_json(output / 'report.json', report)
    def execute(name, argv, cwd=repo, timeout=120):
        result = run_command(argv, cwd, timeout=timeout)
        write_json(output / (name + '.json'), result)
        for stream in ('stdout', 'stderr'):
            (output / (name + '.' + stream + '.log')).write_text(result[stream], encoding='utf-8')
        report['commands'].append({'stage': name, 'evidence': name+'.json',
                                   'exit_code': result['exit_code'], 'duration_seconds': result['duration_seconds']})
        save()
        if not result['successful']:
            raise RuntimeError(f'{name} failed: exit {result["exit_code"]}; see {output / (name+".json")}')
        return result
    save()
    try:
        if os.name != 'posix' or design not in DESIGNS:
            raise ValueError('Linux and an allowlisted upstream example are required')
        for name, directory, revision in [('repository', repo, REVISION),
                ('primitives', repo/'ip/fabulous-tiles', PRIMITIVES_REVISION)]:
            actual = execute(name+'_revision', ['/usr/bin/git', 'rev-parse', 'HEAD'], directory)['stdout'].strip()
            if actual != revision:
                raise ValueError(f'{name} revision mismatch: {actual}')
            dirty = execute(name+'_diff', ['/usr/bin/git', 'diff', 'HEAD', '--'], directory)['stdout']
            if dirty.strip():
                raise ValueError(f'{name} has modified tracked sources')
        # A fresh tree prevents old outputs or parallel builds from being mistaken for this run.
        snapshot = Path(tempfile.mkdtemp(prefix='bmlabs-sky130-'))
        report['source_snapshot'] = str(snapshot)
        source_manifest = {}
        for prefix, paths in [('', ['user_designs', 'ip/extra-tiles']), ('ip/fabulous-tiles', ['primitives'])]:
            directory = repo/prefix
            listing = execute(('repository' if not prefix else 'primitives')+'_files',
                              ['/usr/bin/git', 'ls-files', '-z', '--', *paths], directory)['stdout']
            for name in filter(None, listing.split('\0')):
                source=directory/name
                relative=Path(prefix)/name
                if source.is_symlink() or not source.resolve().is_relative_to(directory.resolve()):
                    raise ValueError(f'Unsupported source link: {relative}')
                destination=snapshot/relative
                destination.parent.mkdir(parents=True,exist_ok=True)
                data=source.read_bytes()
                destination.write_bytes(data)
                source_manifest[relative.as_posix()]=hashlib.sha256(data).hexdigest()
        write_json(output/'source_manifest.json',source_manifest)
        env = ['/usr/bin/env', 'PATH='+tool_path]
        for name, args in [('yosys', ['-V']), ('nextpnr-generic', ['--version']), ('python3', ['--version'])]:
            execute(name+'_version', env+[name, *args])
        execute('python_fasm', env+['python3', '-c', 'import fasm, hashlib, pathlib, importlib.metadata as m; print("version:",m.version("fasm") if m.packages_distributions().get("fasm") else "metadata unavailable"); print(fasm.__file__); print("sha256:",hashlib.sha256(pathlib.Path(fasm.__file__).read_bytes()).hexdigest())'])
        work = snapshot/'user_designs/designs/classic'/design
        # Use the documented per-design targets: parent *-pnr/*-bit suffix rules are broken.
        for stage in ('synth', 'pnr', 'bitstream', 'hex'):
            result=execute(stage, env+['make', stage], work, timeout=600)
            if stage=='pnr':
                report['routing_notes']=[line.strip() for line in (result['stdout']+'\n'+result['stderr']).splitlines()
                                         if re.search(r'Max frequency|unconstrained|Warning:|ERROR:',line)]
        bit = (work/(design+'.bit')).read_bytes()
        report['configuration_validation']=validate_configuration(bit,(work/(design+'.hex')).read_text())
        report['status']='successful'
        report['scope']='Synthesis, placement/routing, FASM conversion and hex export executed. Upstream pnr allows timing failure; hardware readiness is not established.'
    except Exception as exc:
        report['status']='failed'
        report['error']=str(exc)
    # Preserve partial outputs too; snapshot guarantees none came from an earlier run.
    if work:
        for suffix in ('.v', '.sv', '.json', '_out.json', '.fasm', '_log.txt', '.bit', '.hex', '.csv', '.vh', '.vhd', '.dot'):
            path = work/(design+suffix)
            if path.is_file():
                data = path.read_bytes()
                (output/path.name).write_bytes(data)
                report['artifacts'].append(dict(path=path.name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
    save()
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--design', choices=DESIGNS, default='counter')
    parser.add_argument('--tool-path', required=True)
    args=parser.parse_args()
    result=build(args.repo,args.output,args.design,args.tool_path)
    print(json.dumps({'status':result['status'], 'error':result.get('error'), 'output':args.output}))
    sys.exit(0 if result['status']=='successful' else 1)
