"""Read-only probes. The saved snapshot is informational; builds probe again."""
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from django.conf import settings
from .execution import run_command, wsl_command, write_json
from .synthesis import tool_command


def probe():
    root = settings.BASE_DIR
    commands = {
        'app_python': [sys.executable, '-I', '-B', '--version'],
        'python_torch': [settings.COMPILER_PYTHON, '-I', '-B', '-c',
            'import sys,torch,numpy; print(sys.version); print("torch="+torch.__version__); print("numpy="+numpy.__version__)'],
        'iverilog': tool_command('IVERILOG', ['-V']),
        'vvp': tool_command('VVP', ['-V']),
    }
    tools = {}
    for name, argv in commands.items():
        tools[name] = run_command(argv, root, timeout=90) if argv[0] else {'successful': False, 'error': 'Executable not configured'}
    for name, key, flag in [('yosys', 'YOSYS_PATH', '-V'), ('nextpnr', 'NEXTPNR_PATH', '--version')]:
        executable = settings.TOOLCHAIN[key] or shutil.which(name)
        argv = tool_command(key.removesuffix('_PATH'), [flag]) if settings.TOOLCHAIN[key] else [executable, flag]
        tools[name] = run_command(argv, root, 30) if executable else {'successful': False, 'error': 'Executable not configured or found in PATH'}
    try:
        tools['abc'] = run_command(tool_command('ABC', ['-s', '-c', 'version']), root, 30)
    except ValueError as exc:
        tools['abc'] = {'successful': False, 'error': str(exc)}
    from .fabulous_runtime import command as fabulous_command
    for name, executable, flags in [('fabulous', 'FABulous', ['--version']),
                                    ('fabulous_yosys', 'yosys', ['-V']),
                                    ('fabulous_nextpnr', 'nextpnr-generic', ['--version'])]:
        try:
            tools[name] = run_command(fabulous_command(executable, flags, timeout=30), root, 40)
        except ValueError as exc:
            tools[name] = {'successful': False, 'exit_code': None, 'error': str(exc)}
    repo = Path(settings.COMPILER_MODEL_REPO) if settings.COMPILER_MODEL_REPO else None
    required = ['bm_models/core/mapping.py', 'bm_models/vendor/neuromorphic_x1/neuromorphic_x2.py',
        'bm_models/vendor/neuromorphic_x1/Crossbar_array.py', 'bm_models/vendor/neuromorphic_x1/FIFO_IOC.py',
        'bm_models/vendor/neuromorphic_x1/Softmax.py', 'projects/2_building_blocks/Neuromorphic_compiler_V2/compiler/preprocess_onnx.py',
        'projects/2_building_blocks/Neuromorphic_compiler_V2/runtime/global_memory_planner.py']
    missing = [p for p in required if not repo or not (repo/p).is_file()]
    git = shutil.which('git')
    revision = run_command([git, '-C', str(repo), 'rev-parse', 'HEAD'], root, 20) if git and repo and repo.exists() else {}
    return {'checked_at': datetime.now(timezone.utc).isoformat(), 'tools': tools,
        'repositories': {'bmsemi_model': str(repo or ''), 'missing_files': missing, 'revision': revision,
                         'x1': settings.COMPILER_X1_REPO},
        'linear_ready': not missing and all(tools[k]['successful'] for k in ['python_torch', 'iverilog', 'vvp']),
        'synthesis_ready': tools['yosys']['successful'] and tools['abc']['successful'],
        'fabulous_tools_ready': all(tools[k]['successful'] for k in ['fabulous', 'fabulous_yosys', 'fabulous_nextpnr']),
        'limitations': ['Only literal MODEL Linear/int8 input is supported; no arbitrary Python execution.',
            'V2 scheduling and memory figures are prototype estimates.',
            'FABulous requires a configured fabric, compatible tools, constraints and bitstream protocol.',
            'Final BM ASIC ABI and FABulous physical integration are not finalized. The separate linear-fpga-v1 adapter programs the pinned ZCU106 Qwen6 overlay and verifies PL MVM + PS bias/ReLU.']}


def inventory_path():
    return Path(settings.MEDIA_ROOT) / 'compiler-inventory.json'


def refresh():
    data = probe()
    path = inventory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    write_json(temporary, data)
    temporary.replace(path)
    return data


def current():
    try:
        return json.loads(inventory_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'checked_at': None, 'linear_ready': False, 'tools': {}, 'limitations': ['Tool inventory has not been probed.']}
