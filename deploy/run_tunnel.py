"""Supervise the dedicated origin and connector for the Windows logon task."""
import json
import logging
from logging.handlers import RotatingFileHandler
import msvcrt
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from tunnel_health import TunnelHealth

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = Path(os.environ['LOCALAPPDATA']) / 'BMLabsCompiler'
RUNTIME.mkdir(parents=True, exist_ok=True)
lock = (RUNTIME / 'supervisor.lock').open('a+b')
lock.seek(0)
if not lock.read(1):
    lock.write(b'0')
    lock.flush()
lock.seek(0)
try:
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
except OSError:
    sys.exit(0)

handler = RotatingFileHandler(RUNTIME / 'supervisor.log', maxBytes=1024*1024, backupCount=2)
logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(message)s')
python = ROOT / '.venv' / 'Scripts' / 'python.exe'
connector = shutil.which('cloudflared')
config = Path.home() / '.cloudflared' / 'bmlabs-ai-compiler.yml'
if not connector or not config.exists():
    raise RuntimeError('cloudflared and the dedicated tunnel configuration are required.')
commands = {
    'app': [str(python), str(ROOT / 'deploy' / 'serve_tunnel.py')],
    'compiler': [str(python), str(ROOT / 'deploy' / 'serve_tunnel.py'), 'run_build_worker'],
    'tunnel': [connector, 'tunnel', '--config', str(config), 'run'],
}
# Optional resolver for tunneled private DNS traffic. This does not override
# Windows DNS used by cloudflared's initial edge discovery.
for resolver in os.environ.get('BMLABS_TUNNEL_DNS_RESOLVERS', '').split(','):
    if resolver.strip():
        commands['tunnel'].extend(['--dns-resolver-addrs', resolver.strip()])
children = {}
logs = {}
tunnel_health = None
try:
    while True:
        for name, command in commands.items():
            process = children.get(name)
            if process is not None and process.poll() is None:
                if name != 'tunnel' or not tunnel_health.should_restart(time.monotonic()):
                    continue
                logging.warning('Tunnel readiness failed for at least 60 seconds (%s); restarting PID %s',
                                tunnel_health.last_error, process.pid)
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process is not None:
                logging.warning('%s exited with code %s; restarting', name, process.returncode)
                logs[name].close()
            log_path = RUNTIME / (name + '.log')
            if log_path.exists() and log_path.stat().st_size > 10 * 1024 * 1024:
                log_path.replace(RUNTIME / (name + '.previous.log'))
            logs[name] = log_path.open('ab', buffering=0)
            children[name] = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=logs[name], stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
            logging.info('Started %s PID %s', name, children[name].pid)
            if name == 'tunnel':
                tunnel_health = TunnelHealth(time.monotonic())
        state = {'supervisor': os.getpid(), **{name: p.pid for name, p in children.items()}}
        (RUNTIME / 'processes.json').write_text(json.dumps(state))
        time.sleep(5)
finally:
    for process in children.values():
        if process.poll() is None:
            process.terminate()
