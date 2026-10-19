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
import p07_diagnostics as diagnostics
import p08_developer_sources as sources
from p08_automatic.packaging import PackagingMixin
from p08_automatic.issuer import Issuer


def local(path, *, directory=False):
    p = Path(path)
    if not p.is_absolute() or (os.name == 'nt' and str(p).startswith('\\\\.\\')):
        raise RuntimeError('FILESYSTEM_PATH_REQUIRED')
    try:
        if directory:
            import stat
            if not stat.S_ISDIR(p.stat().st_mode):
                raise RuntimeError('DEVELOPER_DIRECTORY_REQUIRED')
        # Canonical identity prevents aliases from bypassing existing-data protection.
        return p.resolve()
    except OSError as error:
        diagnostics.failure('path.resolve', error)
        raise


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


class Developer(PackagingMixin):
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
        self.issuer=Issuer(self)
        from p08_automatic.close_queue import CloseQueue
        self.close_queue=CloseQueue(self.issuer,dev.DEV/'issuance')
        saved=dev.DEV/'automatic-job.json'
        if saved.exists():
            previous=json.loads(saved.read_text(encoding='utf-8'))
            if previous.get('state')=='cancelling':
                self.close_queue.enqueue(previous['id']);previous.update(state='cancelled',error=None)
            elif previous.get('state')=='running':previous.update(state='failed',error='PACKAGE_INTERRUPTED')
            self.job=previous
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
        try:backups = json.loads(local(Path(cfg['backup_dir']) / '777-backups.json').read_text(encoding='utf-8'))
        except (OSError, ValueError, RuntimeError) as error:
            diagnostics.failure("backup.status", error)
            backups = dict(last_success=None)
        with self.job_lock:
            job = json.loads(json.dumps(self.job))
        daily_file=self.root / 'private/daily-backup.json'
        daily=json.loads(local(daily_file).read_text(encoding="utf-8")) if daily_file.exists() else dict(hidden_dir='', daily_hour=23)
        health_file=self.root / 'private/daily-backups.json'
        health=json.loads(local(health_file).read_text(encoding="utf-8")) if health_file.exists() else dict(entries={})
        latest=max(health['entries'], default=None)
        return dict(source=sources.source_status(self), daily=daily, daily_result=health['entries'].get(latest), root=str(self.root), backup_dir=cfg['backup_dir'], ledger_id=cfg['ledger_id'], last_backup=backups.get('last_success'), connection=self.connection(), preferences=self.preferences, job=job, issuer=self.issuer.status())

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
            # Authenticate and validate existing resources before switching the selected host.
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
            local(root.parent, directory=True)
            if root.exists() and (not root.is_dir() or any(root.iterdir())):
                raise RuntimeError('DEVELOPER_EMPTY_DIRECTORY_REQUIRED')
            if root == backup:
                raise RuntimeError('BACKUP_DIRECTORY_CONFLICT')
            user, secret = 'admin', secrets.token_urlsafe(32)
            if root.exists():root.rmdir()  # Explicitly selected empty initialization target.
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
        self.dev.stop_host(self.process)
        self.process = None
        try:
            self.dev.command(['configure-backup', '--root', str(self.root), '--backup-dir', str(target), '--admin', self.user], self.password)
        finally:
            self.process = self.start(self.root)
        return self.status()

    def configure_daily(self, directory, hidden, hour):
        if self.job and self.job['state'] in ['running', 'cancelling']:
            raise RuntimeError('DEVELOPER_BUILD_BUSY')
        diagnostics.event("backup.configure.request", normal_path=directory, hidden_path=hidden, hour=hour)
        target, hidden = local(directory), local(hidden)
        diagnostics.event("backup.configure.resolved", normal_path=str(target), hidden_path=str(hidden))
        if not isinstance(hour, int) or isinstance(hour, bool) or not 0 <= hour <= 23:
            raise RuntimeError('DAILY_BACKUP_CONFIG_INVALID')
        self.dev.stop_host(self.process)
        self.process = None
        try:
            self.dev.command(['configure-daily', '--root', str(self.root), '--backup-dir', str(target), '--hidden-dir', str(hidden), '--daily-hour', str(hour), '--admin', self.user], self.password)
        finally:
            self.process = self.start(self.root)
        return self.status()

    def restore_data(self, package, target):
        if self.job and self.job['state'] in ['running', 'cancelling']:
            raise RuntimeError('DEVELOPER_BUILD_BUSY')
        package, target = local(package), local(target)
        if package.suffix != '.qbackup' or not package.is_file():
            raise RuntimeError('DATA_BACKUP_INVALID')
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise RuntimeError('RESTORE_REQUIRES_NEW_DIRECTORY')
        backup = target.with_name(target.name + '-backups')
        if backup.exists():raise RuntimeError('RESTORE_REQUIRES_NEW_DIRECTORY')
        local(target.parent, directory=True)
        if target.exists():target.rmdir()  # Explicitly selected empty recovery target.
        user, secret = 'recovery-' + uuid.uuid4().hex[:12], secrets.token_urlsafe(32)
        self.dev.command(['restore-data', '--package', str(package), '--root', str(target), '--backup-dir', str(backup), '--host', '127.0.0.1', '--host', 'localhost', '--bind', '127.0.0.1', '--port', str(self.dev.PORT), '--admin', user, '--worker', str(self.dev.ROOT / 'target/release' / ('quote-ledger.exe' if os.name == 'nt' else 'quote-ledger')), '--notices', str(self.dev.ROOT / 'THIRD_PARTY_NOTICES.md')], secret)
        self.remember(target, user, secret)
        # Keep the original host running until the imported host has passed full validation.
        return self.select(str(target), username=user, password=secret)

    def handle(self, data):
        op = data.get('op')
        allowed = {'status','bootstrap','select','backup_directory','daily_backup','restore_data','import_directory','save_package','package','cancel','open_output','retry_package','issuer_status','issuer_prepare','issuer_connect','issuer_open','open_logs','package_status'}
        operation = op if isinstance(op, str) and op in allowed else 'invalid'
        quiet = operation in {'status', 'package_status', 'bootstrap'}
        if not quiet:diagnostics.event('control.start', operation=operation)
        try:
            value = self._handle(data)
            if not quiet:diagnostics.event('control.finish', operation=operation)
            return value
        except Exception as error:
            diagnostics.failure(operation, error)
            raise

    def _handle(self, data):
        with self.lock:
            op = data.get('op')
            if op == 'status':return self.status()
            if op == 'package_status':return self.package_status()
            if op == 'bootstrap':return dict(connection=self.connection(), username=self.user, password=self.password)
            if op == 'select':return self.select(data['root'], initialize=data['initialize'], backup_dir=data['backup_dir'], username=data.get('username'), password=data.get('password'))
            if op == 'backup_directory':return self.configure_backup(data['directory'])
            if op == 'daily_backup':return self.configure_daily(data['directory'], data['hidden'], data['hour'])
            if op == 'import_directory':return sources.import_directory(self, data['root'], data['target'], data['username'], data['password'])
            if op == 'restore_data':return self.restore_data(data['package'], data['target'])
            if op == 'save_package':
                output = package_preferences(data)
                preferences = {**self.preferences, 'output':str(output), 'version':data['version'], 'runtime':data['runtime']}
                replace_json(self.preferences_file, preferences); self.preferences = preferences
                return self.package_status()
            if op == 'package':return self.package(data['delivery'], data['permissions'])
            if op == 'retry_package':return self.package(self.job['delivery'],self.job['permissions'],retry=True)
            if op == 'issuer_status':return self.issuer.status(refresh=True)
            if op == 'issuer_prepare':return self.issuer.prepare(data.get('peer'),data.get('restart',False))
            if op == 'issuer_connect':return self.issuer.connect()
            if op == 'issuer_open':return self.issuer.open_kit()
            if op == 'open_logs':
                if os.name=='nt':os.startfile(str(self.dev.ROOT/'logs'/os.environ['QUOTE777_LOG_SESSION']))
                return self.package_status()
            if op == 'cancel':self.cancel(); return self.package_status()
            if op == 'open_output':
                if os.name != 'nt' or not self.job or self.job['state'] != 'succeeded':raise RuntimeError('DEVELOPER_OUTPUT_UNAVAILABLE')
                os.startfile(str(local(self.job['output'], directory=True)))
                return self.package_status()
            raise RuntimeError('DEVELOPER_OPERATION_INVALID')

    def serve(self):
        self.close_queue.start()
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
                    code = ('PATH_PERMISSION_DENIED' if isinstance(error, PermissionError) else
                            'PATH_UNAVAILABLE' if isinstance(error, FileNotFoundError) else str(error))
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
        self.close_queue.close()
        if self.process:self.dev.stop_host(self.process)
