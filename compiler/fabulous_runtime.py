"""Administrator-configured FABulous runtime, isolated from native Linear tools."""
from pathlib import Path
from django.conf import settings
from .execution import wsl_path


def command(tool, args=(), cwd=None, timeout=180):
    config = settings.FABULOUS_RUNTIME
    if not config.get('distro') or not config.get('venv') or not config.get('cad_bin'):
        raise ValueError('FABulous WSL runtime is not configured (distro, venv and CAD bin required).')
    executables = {'FABulous': config['venv'] + '/bin/FABulous',
                   'python': config['venv'] + '/bin/python',
                   **{name: config['cad_bin'] + '/' + name for name in ['yosys', 'nextpnr-generic', 'iverilog', 'vvp']}}
    if tool not in executables:
        raise ValueError('Unsupported FABulous runtime tool: ' + tool)
    argv = ['wsl.exe', '-d', config['distro'], '-u', config.get('user', 'bmlabs')]
    if cwd is not None:
        argv += ['--cd', path_for_runtime(cwd)]
    return argv + ['--exec', '/usr/bin/timeout', '--signal=KILL', str(timeout),
        '/usr/bin/env', '-i', 'HOME=/home/' + config.get('user', 'bmlabs'),
        'LANG=C.UTF-8', 'PYTHONDONTWRITEBYTECODE=1', 'OMP_NUM_THREADS=1',
        'PATH=' + config['venv'] + '/bin:' + config['cad_bin'] + ':/usr/bin:/bin',
        executables[tool], *map(str, args)]


def path_for_runtime(path):
    p = Path(path)
    distro = settings.FABULOUS_RUNTIME.get('distro', '')
    if p.anchor.rstrip('\\/').casefold() == ('\\\\wsl.localhost\\' + distro).casefold():
        return '/' + p.relative_to(p.anchor).as_posix()
    return wsl_path(p)
