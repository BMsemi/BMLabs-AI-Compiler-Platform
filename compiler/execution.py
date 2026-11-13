"""Bounded execution of administrator-selected tools, never shell commands."""
import json
import os
from pathlib import Path
import subprocess
import time
import signal
from datetime import datetime, timezone


def run_command(argv, cwd, timeout=120, log_limit=4 * 1024 * 1024):
    started = datetime.now(timezone.utc).isoformat()
    begin = time.monotonic()
    # Do not forward application secrets or API credentials to compiler children.
    env = {k: v for k, v in os.environ.items() if k.upper() in
           {'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE',
            'LOCALAPPDATA', 'APPDATA', 'PROGRAMDATA', 'HOME',
            'PROCESSOR_ARCHITECTURE', 'PROCESSOR_ARCHITEW6432', 'NUMBER_OF_PROCESSORS', 'COMSPEC', 'OS'}}
    env['PATH'] = os.path.join(os.environ.get('SystemRoot', 'C:\\Windows'), 'System32') if os.name == 'nt' else '/usr/bin:/bin'
    executable = Path(argv[0])
    if executable.is_absolute():
        env['PATH'] = str(executable.parent) + os.pathsep + env['PATH']
        # Portable OSS CAD Suite keeps dependent DLLs beside bin, in lib.
        library = executable.parent.parent / 'lib'
        if executable.parent.name == 'bin' and library.is_dir():
            env['PATH'] = str(library) + os.pathsep + env['PATH']
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['OMP_NUM_THREADS'] = '1'
    result = dict(argv=list(map(str, argv)), cwd=str(cwd), started_at=started,
                  exit_code=None, stdout='', stderr='', timed_out=False)
    import tempfile
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = None
        try:
            process = subprocess.Popen(result['argv'], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                start_new_session=os.name != 'nt')
            while process.poll() is None:
                if time.monotonic() - begin > timeout or max(os.fstat(stdout.fileno()).st_size, os.fstat(stderr.fileno()).st_size) > log_limit:
                    result['timed_out'] = time.monotonic() - begin > timeout
                    result['error'] = 'Execution timeout' if result['timed_out'] else 'Output limit exceeded'
                    if os.name == 'nt':
                        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=15)
                    break
                time.sleep(0.1)
            result['exit_code'] = process.returncode
        except (OSError, subprocess.SubprocessError) as exc:
            result['error'] = str(exc)
            if process and process.poll() is None:
                process.kill()
                process.wait()
        for name, handle in [('stdout', stdout), ('stderr', stderr)]:
            if os.fstat(handle.fileno()).st_size > log_limit:
                result['error'] = 'Output limit exceeded'
            handle.seek(0)
            raw = handle.read(log_limit)
            encoding = 'utf-16-le' if raw[:200].count(b'\0') > 20 else 'utf-8'
            result[name] = raw.decode(encoding, errors='replace')
    result['duration_seconds'] = round(time.monotonic() - begin, 4)
    result['completed_at'] = datetime.now(timezone.utc).isoformat()
    result['successful'] = result['exit_code'] == 0 and not result.get('error')
    return result


def wsl_path(path):
    p = Path(path).resolve()
    if len(p.drive) != 2 or p.drive[1] != ':':
        raise ValueError('WSL builds require a local Windows drive path.')
    return '/mnt/' + p.drive[0].lower() + p.as_posix()[2:]


def wsl_command(distro, argv, timeout=60):
    return ['wsl.exe', '-d', distro, '--exec', '/usr/bin/timeout', '--signal=KILL', str(timeout), *argv]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2), encoding='utf-8')
