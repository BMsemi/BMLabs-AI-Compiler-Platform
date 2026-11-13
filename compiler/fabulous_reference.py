"""Executable upstream demonstration, explicitly separate from BM ASIC targets."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid
import zipfile
from django.conf import settings
from .execution import write_json
from .fabulous_runtime import command as runtime_command, path_for_runtime

DESIGN = 'sequential_16bit_en'
MARKER = 'BMLABS_FABRIC_REFERENCE_PASS comparisons=100'
SCOPE = 'FABulous 2.2.0 upstream counter/reference fabric only; no BM ASIC target, X2 binding or physical programming.'


def required_files(root, names):
    for name in names:
        p = root/name
        if not p.is_file() or not p.stat().st_size:
            raise ValueError('FABulous did not produce a nonempty ' + name)


def validate_simulation(stdout):
    if MARKER not in stdout.splitlines():
        raise ValueError('Configured fabric simulation did not report its completion marker.')
    rows = re.findall(r'fabric\(I_top\) = 0x(\S+) gold = 0x(\S+), fabric\(T_top\) = 0x(\S+) gold = 0x(\S+)', stdout)
    if len(rows) != 100:
        raise ValueError('Expected exactly 100 configured-fabric comparisons.')
    values = []
    for row in rows:
        if any(not re.fullmatch('[0-9a-fA-F]+', x) for x in row):
            raise ValueError('Unknown or high-impedance bits in fabric comparison.')
        actual, golden, direction, golden_direction = [int(x, 16) for x in row]
        if actual != golden or direction != golden_direction or direction != 0xffffffe:
            raise ValueError('Configured fabric differs from its counter/direction oracle.')
        values.append(actual)
    if values != list(range(100)):
        raise ValueError('Configured counter does not match the independent reset/count sequence 0 through 99.')
    return {'status': 'passed', 'comparisons': len(rows), 'first_count': values[0],
            'last_count': values[-1], 'scope': SCOPE}


def verify_hex(binary, hex_path):
    data = binary.read_bytes()
    if not data or len(data) > 16384 or len(data) % 4:
        raise ValueError('Reference bitstream must contain aligned words within the loader capacity.')
    try:
        loaded = bytes(int(v, 16) for v in hex_path.read_text().split())
    except (ValueError, OSError) as exc:
        raise ValueError('Invalid simulator bitstream hex file.') from exc
    if len(loaded) != 16384 or loaded[:len(data)] != data or any(loaded[len(data):]):
        raise ValueError('Simulator hex does not preserve the exact generated binary plus zero padding.')
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'hex_sha256': hashlib.sha256(hex_path.read_bytes()).hexdigest()}


def archive_project(root, work):
    if not root.is_dir():
        return
    files = [p for p in sorted(root.rglob('*')) if p.is_file()]
    if any(p.is_symlink() or not p.resolve().is_relative_to(root.resolve()) for p in files):
        raise ValueError('Unexpected link in generated reference project.')
    # Simulator executables are text-heavy; retain them losslessly in the ZIP.
    # Bound both uncompressed work and the stored archive independently.
    if sum(p.stat().st_size for p in files) > 4 * settings.COMPILER_MAX_ARTIFACT_BYTES:
        raise ValueError('Reference work exceeds the uncompressed limit; files retained at ' + str(root))
    manifest = {}
    with zipfile.ZipFile(work/'reference_project.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for p in files:
            name = p.relative_to(root).as_posix()
            with p.open('rb') as handle:
                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
            manifest[name] = {'sha256': digest, 'bytes': p.stat().st_size}
            archive.write(p, name)
    if (work/'reference_project.zip').stat().st_size > settings.COMPILER_MAX_ARTIFACT_BYTES:
        raise ValueError('Reference archive exceeds artifact quota; files retained at ' + str(root))
    write_json(work/'reference_files.json', {'scope': SCOPE, 'directory': str(root), 'files': manifest})
    for suffix in ['bin', 'fasm', 'json']:
        p = root/'user_design'/f'{DESIGN}.{suffix}'
        if p.is_file():
            shutil.copyfile(p, work/f'reference_counter.{suffix}')


def run(work, execute):
    configured = settings.FABULOUS_WORK_ROOT
    if not configured:
        raise ValueError('FABULOUS_WORK_ROOT is not configured.')
    root = Path(configured).resolve()
    expected = Path('//wsl.localhost/' + settings.FABULOUS_RUNTIME['distro'] + '/home/' + settings.FABULOUS_RUNTIME.get('user', 'bmlabs') + '/work')
    if not root.is_relative_to(expected) or not root.is_dir() or any(c.isspace() for c in str(root)):
        raise ValueError('FABULOUS_WORK_ROOT must be an existing directory under the configured Linux user work directory.')
    host_storage = settings.FABULOUS_HOST_STORAGE
    if not host_storage or not Path(host_storage).is_dir():
        raise ValueError('FABULOUS_HOST_STORAGE must identify the host directory containing this compiler distribution.')
    if min(shutil.disk_usage(host_storage).free, shutil.disk_usage(work).free) < 2 * 1024**3:
        raise ValueError('FABulous needs at least 2 GiB free on its host work drive.')
    project = root/str(uuid.UUID(work.name))
    if project.exists():
        raise ValueError('Reference build directory already exists; stale outputs cannot be reused.')
    project_arg = path_for_runtime(project)

    def cli(name, text, timeout=180):
        return execute(name, runtime_command('FABulous', ['-p', project_arg, 'run', text], timeout=timeout), timeout+15)

    try:
        version = execute('reference_version', runtime_command('FABulous', ['--version'], timeout=30), 45)
        if version['stdout'].strip() != 'FABulous CLI 2.2.0':
            raise ValueError('Reference adapter requires the tested FABulous 2.2.0 template.')
        execute('reference_create', runtime_command('FABulous', ['create-project', project_arg], timeout=90), 105)
        required_files(project, ['fabric.csv', f'Test/{DESIGN}_tb.v', f'user_design/{DESIGN}.v'])
        template_hashes = {p.relative_to(project).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(project.rglob('*')) if p.is_file()}
        write_json(work/'reference_template.json', {'package': 'fabulous-fpga==2.2.0', 'files': template_hashes, 'scope': SCOPE})
        tb = project/'Test'/f'{DESIGN}_tb.v'
        source = tb.read_text(encoding='utf-8')
        if source.count('else $finish;') != 1:
            raise ValueError('Upstream reference scoreboard has changed; review required.')
        tb.write_text(source.replace('else $finish;', f'else begin $display("{MARKER}"); $finish; end'), encoding='utf-8', newline='\n')
        cli('reference_fabric', 'run_fab', 240)
        required_files(project, ['Fabric/eFPGA.v', 'Fabric/eFPGA_top.v', '.FABulous/bitStreamSpec.bin', '.FABulous/pips.txt', '.FABulous/bel.txt'])
        cli('reference_synthesis', f'compile_design --synth-only user_design/{DESIGN}.v')
        required_files(project, [f'user_design/{DESIGN}.json'])
        netlist = json.loads((project/'user_design'/f'{DESIGN}.json').read_text())
        if not netlist.get('modules', {}).get('top_wrapper', {}).get('cells'):
            raise ValueError('Reference synthesis produced no mapped top-level cells.')
        cli('reference_place_route', f'compile_design --pnr-only user_design/{DESIGN}.v')
        required_files(project, [f'user_design/{DESIGN}.fasm'])
        cli('reference_bitstream', f'compile_design --bitgen-only user_design/{DESIGN}.v')
        binary = project/'user_design'/f'{DESIGN}.bin'
        required_files(project, [f'user_design/{DESIGN}.bin'])
        bitstream = verify_hex(binary, project/'Test/build'/f'{DESIGN}.hex')
        result = cli('reference_simulation', f'run_simulation fst user_design/{DESIGN}.bin', 300)
        report = validate_simulation(result['stdout'])
        if verify_hex(binary, project/'Test/build'/f'{DESIGN}.hex') != bitstream:
            raise ValueError('The binary or loaded hex changed during simulation.')
        report['bitstream'] = bitstream
        write_json(work/'reference_verification.json', report)
        return report
    finally:
        archive_project(project, work)
