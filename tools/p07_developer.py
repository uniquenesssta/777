"""Private loopback control for the Windows development launcher, not a service API."""
import hashlib
import hmac
import json
import os
import queue
from pathlib import Path
import re
import secrets
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from quote_service.journal import dpapi


def local(path, *, directory=False):
    p = Path(path)
    if not p.is_absolute() or str(p).startswith(('\\\\', '//')):
        raise RuntimeError('DEVELOPER_LOCAL_PATH_REQUIRED')
    for ancestor in [p, *p.parents]:
        if ancestor.is_symlink() or (ancestor.exists() and getattr(ancestor.stat(), 'st_file_attributes', 0) & 0x400):
            raise RuntimeError('DEVELOPER_PATH_REPARSE_POINT')
    if directory and not p.is_dir():
        raise RuntimeError('DEVELOPER_DIRECTORY_REQUIRED')
    return p.resolve()


def replace_json(path, value):
    local(path.parent, directory=True)
    local(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def package_preferences(value):
    if not isinstance(value.get('version'), str) or not re.fullmatch(r'\d+\.\d+\.\d+', value['version']) or value.get('runtime') not in ['downloadBootstrapper','offlineInstaller']:
        raise RuntimeError('DEVELOPER_PACKAGE_CONFIG_INVALID')
    return local(value['output'])


class Developer:
    def __init__(self, dev, initial, process):
        self.dev, self.root, self.process = dev, local(initial, directory=True), process
        self.lock = threading.RLock()
        self.job_lock = threading.Lock()
        self.job = None
        self.worker = None
        self.build = None
        self.build_owner = None
        self.cancelled = threading.Event()
        self.token = secrets.token_urlsafe(48)
        self.user, self.password = 'admin', '123456'
        self.preferences_file = dev.DEV / 'developer.json'
        self.credentials_file = dev.DEV / 'developer-credentials.bin'
        self.preferences = dict(schema='777-developer-v1', root=str(self.root), output=str(dev.DEV / 'packages'), version='0.1.0', runtime='downloadBootstrapper')
        self.credentials = {}
        if self.credentials_file.exists():
            if local(self.credentials_file).stat().st_size > 2 * 1024 * 1024:raise RuntimeError('DEVELOPER_CONFIG_INVALID')
            raw = local(self.credentials_file).read_bytes()
            self.credentials = json.loads(dpapi(raw, decrypt=True) if os.name == 'nt' else raw)
        if self.preferences_file.exists():
            if local(self.preferences_file).stat().st_size > 65536:raise RuntimeError('DEVELOPER_CONFIG_INVALID')
            value = json.loads(local(self.preferences_file).read_text(encoding='utf-8'))
            if set(value) != set(self.preferences) or value['schema'] != '777-developer-v1':
                raise RuntimeError('DEVELOPER_CONFIG_INVALID')
            self.preferences = value
            local(value['root'])
            package_preferences(value)
        self.server = None

    def config(self, root=None):
        root = local(root or self.root, directory=True)
        cfg = json.loads(local(root / 'private/service.json').read_text(encoding='utf-8'))
        if cfg['bind'] != '127.0.0.1' or cfg['port'] != self.dev.PORT or cfg['maintenance']:
            raise RuntimeError('DEVELOPER_LOOPBACK_HOST_REQUIRED')
        return cfg

    def connection(self):
        cfg = self.config()
        return dict(url=f'https://127.0.0.1:{self.dev.PORT}', certificate_pem=local(self.root / 'service-cert.pem').read_text(encoding='utf-8'), certificate_sha256=cfg['certificate_sha256'])

    def status(self):
        cfg = self.config()
        backups = json.loads(local(Path(cfg['backup_dir']) / '777-backups.json').read_text(encoding='utf-8'))
        with self.job_lock:
            job = json.loads(json.dumps(self.job))
        return dict(root=str(self.root), backup_dir=cfg['backup_dir'], ledger_id=cfg['ledger_id'], last_backup=backups.get('last_success'), connection=self.connection(), preferences=self.preferences, job=job)

    def remember(self, root, user, password):
        root = local(root, directory=True)
        cfg = self.config(root)
        credentials = {**self.credentials, str(root):dict(user=user, password=password, pin=cfg['certificate_sha256'])}
        raw = json.dumps(credentials).encode()
        if os.name == 'nt':
            raw = dpapi(raw)
        # The non-Windows mode is the launcher's explicit isolated auxiliary runner.
        temp = self.credentials_file.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        local(self.credentials_file)
        try:
            with temp.open('xb') as stream:
                if os.name != 'nt':os.chmod(temp, 0o600)
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, self.credentials_file)
        finally:temp.unlink(missing_ok=True)
        self.credentials = credentials

    def upgrade(self, root, user, secret):
        cfg = self.config(root)
        binary = self.dev.ROOT / 'target/release' / ('quote-host.exe' if os.name == 'nt' else 'quote-host')
        worker = binary.with_name('quote-ledger.exe' if os.name == 'nt' else 'quote-ledger')
        if cfg.get('rust_host_sha256') != hashlib.sha256(binary.read_bytes()).hexdigest() or cfg.get('rust_worker_sha256') != hashlib.sha256(worker.read_bytes()).hexdigest():
            # Existing host selection takes a verified maintenance backup before resource upgrades.
            self.dev.command(['select-host', '--root', str(root), '--admin', user, '--backend', 'rust', '--worker', str(worker), '--notices', str(self.dev.ROOT / 'THIRD_PARTY_NOTICES.md'), '--upgrade-resources'], secret)

    def start(self, root):
        self.config(root)
        cmd = [str(self.dev.ROOT / 'target/release' / ('quote-host.exe' if os.name == 'nt' else 'quote-host')), 'run', '--root', str(root), '--isolated-test', '--test-shutdown-stdin']
        if os.name != 'nt':cmd.append('--auxiliary')
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0, start_new_session=os.name != 'nt')
        try:
            lines = queue.Queue()
            threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
            try:ready = json.loads(lines.get(timeout=30))
            except queue.Empty:raise RuntimeError('DEVELOPMENT_HOST_NOT_READY')
            if ready.get('status') != 'ready':raise RuntimeError('DEVELOPMENT_HOST_NOT_READY')
            return process
        except BaseException:
            self.dev.stop_host(process)
            raise

    def select(self, root, *, initialize=False, backup_dir='', username=None, password=None):
        root = local(root)
        if self.job and self.job['state'] in ['running', 'cancelling']:
            raise RuntimeError('DEVELOPER_BUILD_BUSY')
        if root == self.root:
            if initialize:raise RuntimeError('DEVELOPER_DATA_EXISTS')
            return self.status()
        if initialize:
            backup = local(backup_dir)
            for p in [root, backup]:
                local(p.parent, directory=True)
                if p.exists() and (not p.is_dir() or any(p.iterdir())):
                    raise RuntimeError('DEVELOPER_EMPTY_DIRECTORY_REQUIRED')
            if root == backup or root in backup.parents or backup in root.parents:
                raise RuntimeError('BACKUP_DIRECTORY_CONFLICT')
            user, secret = 'admin', secrets.token_urlsafe(32)
            for p in [root, backup]:
                if p.exists():p.rmdir()  # Explicitly selected, verified empty initialization targets.
            self.dev.command(['init', '--root', str(root), '--backup-dir', str(backup), '--host', '127.0.0.1', '--host', 'localhost', '--bind', '127.0.0.1', '--port', str(self.dev.PORT), '--admin', user, '--worker', str(self.dev.ROOT / 'target/release' / ('quote-ledger.exe' if os.name == 'nt' else 'quote-ledger')), '--notices', str(self.dev.ROOT / 'THIRD_PARTY_NOTICES.md')], secret)
        else:
            cfg = self.config(root)
            remembered = self.credentials.get(str(root))
            if username and password:
                user, secret = username, password
            elif root == local(self.dev.DEV / 'host'):
                user, secret = 'admin', '123456'
            elif remembered and remembered['pin'] == cfg['certificate_sha256']:
                user, secret = remembered['user'], remembered['password']
            else:
                raise RuntimeError('DEVELOPER_CREDENTIAL_REQUIRED')
            self.dev.command(['authorize', '--root', str(root), '--admin', user], secret)
        self.upgrade(root, user, secret)
        self.remember(root, user, secret)
        previous = (self.root, self.user, self.password)
        self.dev.stop_host(self.process)
        self.process = None
        try:
            self.process = self.start(root)
            self.root, self.user, self.password = root, user, secret
            preferences = {**self.preferences, 'root':str(root)}
            replace_json(self.preferences_file, preferences)
            self.preferences = preferences
        except BaseException:
            if self.process:self.dev.stop_host(self.process)
            self.root, self.user, self.password = previous
            self.process = self.start(self.root)
            raise
        return self.status()

    def configure_backup(self, directory):
        if self.job and self.job['state'] in ['running', 'cancelling']:
            raise RuntimeError('DEVELOPER_BUILD_BUSY')
        target = local(directory)
        if target == local(self.config()['backup_dir']):return self.status()
        self.dev.stop_host(self.process)
        self.process = None
        try:
            self.dev.command(['configure-backup', '--root', str(self.root), '--backup-dir', str(target), '--admin', self.user], self.password)
        finally:
            self.process = self.start(self.root)
        return self.status()

    def package(self, delivery, connection):
        if os.name != 'nt':raise RuntimeError('WINDOWS_PACKAGING_REQUIRED')
        if delivery not in ['manager', 'sales']:raise RuntimeError('DELIVERY_REQUIRED')
        with self.job_lock:
            if self.job and self.job['state'] in ['running', 'cancelling']:raise RuntimeError('DEVELOPER_BUILD_BUSY')
            output = package_preferences(self.preferences)
            for protected in map(local, [self.root, Path(self.config()['backup_dir']), self.dev.ROOT]):
                if output == protected or protected in output.parents or output in protected.parents:
                    raise RuntimeError('DEVELOPER_OUTPUT_CONFLICT')
            output.mkdir(parents=True, exist_ok=True)
            local(output, directory=True)
            key = uuid.uuid4().hex
            destination = output / f'{delivery}-{self.preferences["version"]}-{key[:8]}'
            public = {k:connection[k] for k in ['url','certificate_pem','certificate_sha256']}
            source = self.dev.DEV / ('package-connection-' + key + '.json')
            replace_json(source, {'schema':'777-public-connection-v1', 'connection':public})
            self.job = dict(id=key, state='running', delivery=delivery, version=self.preferences['version'], output=str(destination), lines=[], error=None, bytes=None)
            self.cancelled.clear()
            args = [os.environ.get('QUOTE777_NODE') or 'node', str(self.dev.ROOT / 'desktop/tools/package.mjs'), '--delivery', delivery, '--connection', str(source), '--output', str(destination), '--version', self.preferences['version'], '--webview', self.preferences['runtime']]
            self.worker = threading.Thread(target=self.build_package, args=(args, source, destination), daemon=False)
            self.worker.start()
        return self.status()

    def build_package(self, args, source, destination):
        try:
            from p07_owned_job import OwnedJob
            with self.job_lock:
                if self.cancelled.is_set():
                    self.job.update(state='cancelled', error=None)
                    return
                self.build_owner = OwnedJob()
                self.build = subprocess.Popen(args, cwd=self.dev.ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                                              env=dict(os.environ, QUOTE777_PACKAGE_CONTROL_STDIN='1'))
                process = self.build
                # Node waits on this private pipe until the job owns all future descendants.
                self.build_owner.assign(process)
                process.stdin.write(b'start\n'); process.stdin.flush(); process.stdin.close()
            for line in iter(process.stdout.readline, b''):
                with self.job_lock:
                    self.job['lines'] = (self.job['lines'] + [line.decode('utf-8', 'replace').rstrip()[-2000:]])[-80:]
            code = process.wait()
            if self.cancelled.is_set():state, error = 'cancelled', None
            elif code:state, error = 'failed', 'TAURI_BUILD_FAILED'
            else:
                manifest = json.loads((destination / 'release.json').read_text(encoding='utf-8'))
                if manifest['delivery'] != self.job['delivery']:raise RuntimeError('COMPILED_PACKAGE_MISMATCH')
                state, error = 'succeeded', None
                with self.job_lock:
                    self.job['bytes'] = sum(p.stat().st_size for p in destination.iterdir() if p.is_file())
                    self.job['source_commit'] = manifest['source_commit']
            with self.job_lock:self.job.update(state=state, error=error)
        except Exception:
            with self.job_lock:self.job.update(state='cancelled' if self.cancelled.is_set() else 'failed', error='DEVELOPER_BUILD_FAILED')
        finally:
            with self.job_lock:
                if self.build_owner:self.build_owner.close(); self.build_owner = None
                process = self.build
                self.build = None
            if process and process.poll() is None:process.kill(); process.wait(timeout=15)
            source.unlink(missing_ok=True)

    def cancel(self):
        with self.job_lock:
            if not self.job or self.job['state'] not in ['running', 'cancelling']:return
            self.cancelled.set(); self.job['state'] = 'cancelling'
            if self.build_owner:self.build_owner.close(); self.build_owner = None

    def handle(self, data):
        with self.lock:
            op = data.get('op')
            if op == 'status':return self.status()
            if op == 'bootstrap':return dict(connection=self.connection(), username=self.user, password=self.password)
            if op == 'select':return self.select(data['root'], initialize=data['initialize'], backup_dir=data['backup_dir'], username=data.get('username'), password=data.get('password'))
            if op == 'backup_directory':return self.configure_backup(data['directory'])
            if op == 'save_package':
                output = package_preferences(data)
                preferences = {**self.preferences, 'output':str(output), 'version':data['version'], 'runtime':data['runtime']}
                replace_json(self.preferences_file, preferences); self.preferences = preferences
                return self.status()
            if op == 'package':return self.package(data['delivery'], data['connection'])
            if op == 'cancel':self.cancel(); return self.status()
            if op == 'open_output':
                if os.name != 'nt' or not self.job or self.job['state'] != 'succeeded':raise RuntimeError('DEVELOPER_OUTPUT_UNAVAILABLE')
                os.startfile(str(local(self.job['output'], directory=True)))
                return self.status()
            raise RuntimeError('DEVELOPER_OPERATION_INVALID')

    def serve(self):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):pass
            def do_POST(self):
                self.connection.settimeout(5)
                if self.path != '/control' or self.headers.get('Origin') or not hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer ' + owner.token):
                    self.send_error(403); return
                try:
                    length = int(self.headers.get('Content-Length','0'))
                    if length <= 0 or length > 65536:raise RuntimeError('DEVELOPER_REQUEST_INVALID')
                    value = owner.handle(json.loads(self.rfile.read(length)))
                    result = {'value':value}
                except Exception as error:
                    code = str(error)
                    # CLI failures are structured JSON; never return arbitrary exception text/secrets.
                    try:code = json.loads(code)['error']
                    except (ValueError, KeyError, TypeError):pass
                    result = {'error':code if re.fullmatch('[A-Z][A-Z0-9_]{1,100}', code) else 'DEVELOPER_OPERATION_FAILED'}
                raw = json.dumps(result).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = False
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        os.environ['QUOTE777_DEVELOPER_PORT'] = str(self.server.server_port)
        os.environ['QUOTE777_DEVELOPER_TOKEN'] = self.token

    def close(self):
        if self.server:self.server.shutdown(); self.server.server_close()
        self.cancel()
        if self.worker:self.worker.join(timeout=25)
        if self.worker and self.worker.is_alive():raise RuntimeError('DEVELOPER_BUILD_CLEANUP_FAILED')
        if self.process:self.dev.stop_host(self.process)
