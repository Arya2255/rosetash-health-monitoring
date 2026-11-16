"""Start the bundled local services and keep state outside onefile extraction.

Only frozen Windows builds bootstrap automatically. Source runs keep their
existing services unless ROZTASH_PORTABLE=1 is explicitly requested for tests.
"""
from __future__ import annotations
import atexit
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

_OWNER = None
_ROOT = None


def portable_enabled():
    return ((sys.platform == 'win32' and getattr(sys, 'frozen', False))
            or os.environ.get('ROZTASH_PORTABLE') == '1')


def should_bootstrap():
    return portable_enabled() and not os.environ.get('ROZTASH_CHILD_WORKER')


def resources():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))


def configure_state(root=None):
    root = Path(root or os.environ.get('ROZTASH_HOME') or
                Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'Roztash')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == 'nt' and portable_enabled():
        # Per-user private state, including mail credentials and health records.
        who = subprocess.check_output(['whoami','/user','/fo','csv','/nh'],
                                      text=True, **hidden_process())
        import csv
        sid = next(csv.reader([who.strip()]))[-1]
        result = subprocess.run(['icacls',str(root),'/inheritance:r','/grant:r',
                                 '*'+sid+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F'],
                                capture_output=True, **hidden_process())
        if result.returncode:
            raise RuntimeError('Cannot protect private application state')
    defaults = {
        'ROZTASH_HOME': str(root), 'ROZTASH_CONFIG_HOME': str(root),
        'ROZTASH_CF_HOME': str(root/'cloudflared'),
        'ROZTASH_BRIDGE_DB': str(root/'state/live.db'),
        'ROZTASH_BRIDGE_AUTH_FILE': str(root/'bridge-auth.key'),
        'ROZTASH_LOG_DIR': str(root/'logs'),
        'ROZTASH_BRIDGE': 'http://127.0.0.1:8726',
        'ROZTASH_MQTT_HOST': '127.0.0.1', 'ROZTASH_MQTT_PORT': '1884',
        'ROZTASH_BRIDGE_HOST': '127.0.0.1', 'ROZTASH_BRIDGE_PORT': '8726',
    }
    for name, value in defaults.items():
        os.environ.setdefault(name, value)
    for name in ('cloudflared','logs','state/photos','run'):
        (root/name).mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def hidden_process():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def stage_runtime(root):
    """Cache only digest-verified immutable tools, not arbitrary DLLs on PATH."""
    source = resources()/'runtime/windows'
    if not source.is_dir():
        if os.name != 'nt':
            return None
        raise RuntimeError('Bundled Windows runtime is missing')
    manifest_path = source/'runtime-manifest.json'
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    version = hashlib.sha256(manifest_bytes).hexdigest()[:16]
    target = root/'runtime'/version
    for name, expected in manifest.items():
        parts = Path(name).parts
        if Path(name).is_absolute() or '..' in parts:
            raise ValueError('Invalid runtime file path')
        original, dest = source/name, target/name
        if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest() == expected['sha256']:
            continue
        data = original.read_bytes()
        if len(data) != expected['size'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise ValueError('Bundled tool checksum mismatch')
        dest.parent.mkdir(parents=True, exist_ok=True)
        pending = dest.with_name(dest.name + '.new-' + str(os.getpid()))
        pending.write_bytes(data)
        pending.replace(dest)
    for name, filename in (('ROZTASH_MOSQUITTO_SUB','mosquitto_sub.exe'),
                           ('ROZTASH_MOSQUITTO_PUB','mosquitto_pub.exe')):
        os.environ.setdefault(name, str(target/'mosquitto'/filename))
    os.environ.setdefault('ROZTASH_CLOUDFLARED', str(target/'cloudflared.exe'))
    return target


def initialize():
    global _ROOT
    if _ROOT is not None:
        return _ROOT
    root = configure_state()
    if getattr(sys, 'frozen', False):
        from private_profile import install_profile
        install_profile(sys.executable, root)
    stage_runtime(root)
    _ROOT = root
    return root


def worker_command(kind):
    flag = '--worker-' + kind
    if getattr(sys, 'frozen', False):
        return [sys.executable, flag]
    return [sys.executable, '-B', str(Path(__file__).with_name('main.py')), flag]


def prepare_entrypoint():
    """Called before importing modules that resolve configuration paths."""
    if not portable_enabled():
        return
    root = initialize()
    if '--worker-bridge' in sys.argv:
        os.environ['ROZTASH_CHILD_WORKER'] = 'bridge'
        # Imported lazily so normal imports never open the database.
        from backend.bridge import main
        main()
        raise SystemExit(0)
    if '--worker-web' in sys.argv:
        os.environ['ROZTASH_CHILD_WORKER'] = 'web'
        os.environ['FLET_FORCE_WEB_SERVER'] = 'true'
    if '--inspect-install' in sys.argv:
        # Nonsecret readiness only; usable in CI with a synthetic seed.
        cfgpath = Path(os.environ['ROZTASH_CF_HOME'])/'rosetash-remote.json'
        cfg = json.loads(cfgpath.read_text()) if cfgpath.exists() else {}
        smtp = cfg.get('smtp', {})
        result = {'smtp_configured': bool(smtp.get('user') and smtp.get('password')),
                  'database_present': Path(os.environ['ROZTASH_BRIDGE_DB']).is_file(),
                  'broker_bundled': bool(tool_path('mosquitto')),
                  'tunnel_bundled': bool(os.environ.get('ROZTASH_CLOUDFLARED')),
                  'state_dir': str(root)}
        (root/'install-check.json').write_text(json.dumps(result), encoding='utf-8')
        raise SystemExit(0)


def tool_path(name):
    if _ROOT:
        source = resources()/'runtime/windows/runtime-manifest.json'
        if source.exists():
            version = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
            p = _ROOT/'runtime'/version/'mosquitto'/(name+'.exe')
            if p.is_file():
                return str(p)
    return shutil.which(name)


def bridge_healthy():
    try:
        url = os.environ.get('ROZTASH_BRIDGE','http://127.0.0.1:8726') + '/health'
        with urllib.request.urlopen(url,timeout=1) as response:
            body = json.load(response)
            return bool(body.get('ok') and 'db' in body)
    except Exception:
        return False


def web_healthy():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8550/',timeout=1) as response:
            return b'flutter_bootstrap.js' in response.read(65536)
    except Exception:
        return False


def port_open(host, port):
    try:
        with socket.create_connection((host,int(port)),timeout=.5):
            return True
    except OSError:
        return False


class LocalServices:
    def __init__(self, root):
        self.root = Path(root)
        self.children = []
        self.files = []
        self.broker = None
        self.lock = None

    def acquire(self):
        self.lock = (self.root/'run'/'services.lock').open('a+b')
        self.lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close(); self.lock = None
            raise RuntimeError('Roztash is already running. Use its existing window.')

    def spawn(self, args, name):
        log = (self.root/'logs'/('service-'+name+'.log')).open('ab', buffering=0)
        self.files.append(log)
        env = dict(os.environ)
        # Re-executing a onefile child must have an independent extraction dir.
        env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
        proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                                env=env, cwd=str(self.root), **hidden_process())
        self.children.append(proc)
        return proc

    def wait(self, ready, proc, name):
        deadline = time.monotonic()+35
        while time.monotonic()<deadline:
            if proc.poll() is not None:
                raise RuntimeError(name+' exited; see service log')
            if ready():
                return
            time.sleep(.2)
        raise RuntimeError(name+' did not become ready; see service log')

    def start_broker(self):
        host = os.environ.get('ROZTASH_MQTT_HOST','127.0.0.1')
        port = int(os.environ.get('ROZTASH_MQTT_PORT','1884'))
        if host not in ('127.0.0.1','localhost'):
            return
        if port_open(host,port):
            # Reuse a configured broker; never kill someone else's process.
            return
        tool = tool_path('mosquitto')
        if not tool:
            raise RuntimeError('Bundled MQTT broker not found')
        cfg = self.root/'run/mosquitto.conf'
        # Gateway firmware currently uses the trusted local LAN without login.
        # Windows firewall access should be allowed only on private networks.
        cfg.write_text(f'listener {port} 0.0.0.0\nallow_anonymous true\npersistence false\n',encoding='utf-8')
        self.broker = self.spawn([tool,'-c',str(cfg)],'mqtt')
        self.wait(lambda:port_open(host,port),self.broker,'MQTT broker')

    def start_bridge(self):
        if bridge_healthy():
            return
        self.start_broker()
        proc = self.spawn(worker_command('bridge'),'bridge')
        self.wait(bridge_healthy,proc,'Data bridge')

    def start_web(self):
        if web_healthy():
            return
        proc = self.spawn(worker_command('web'),'web')
        self.wait(web_healthy,proc,'Web server')

    def close(self):
        for proc in reversed(self.children):
            if proc.poll() is None:
                if os.name == 'nt':
                    try:
                        subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],
                                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                       timeout=8,**hidden_process())
                    except (OSError, subprocess.TimeoutExpired):
                        proc.terminate()
                else:
                    proc.terminate()
                    try: proc.wait(timeout=4)
                    except subprocess.TimeoutExpired: proc.kill()
        self.children.clear()
        for stream in self.files:
            stream.close()
        self.files.clear()
        if self.lock:
            self.lock.close()
            self.lock = None


def start_services(web=False):
    global _OWNER
    if not should_bootstrap():
        return None
    root = initialize()
    services = LocalServices(root)
    try:
        services.acquire()
        services.start_bridge()
        if not web:
            services.start_web()
    except Exception:
        services.close()
        raise
    _OWNER = services
    atexit.register(services.close)
    return services
