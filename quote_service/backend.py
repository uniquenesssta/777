"""Explicit offline financial-backend selection under the existing host-owner lock."""
import os
import shutil
from pathlib import Path
from quote_files.transactions import file_lock
from quote_ledger import Ledger
from quote_ledger.backup import publish_json,read_json
from quote_ledger.paths import local_path,Conflict
from .protocol import APIError
from .rust_ledger import RustLedger,WORKER,NOTICES,RUST_FILES,file_hash


def selected(private,config,*,auxiliary=False):
    backend=config.get('ledger_backend','python')
    if backend not in {'python','rust'}:raise APIError(422,'HOST_BACKEND_INVALID')
    if backend=='python':return Ledger(private/'ledger.sqlite3')
    sha=config.get('rust_worker_sha256')
    if type(sha) is not str or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):raise APIError(422,'HOST_WORKER_INVALID')
    local_path(private/NOTICES)
    return RustLedger(private/'ledger.sqlite3',private/WORKER,auxiliary=auxiliary,expected_sha256=sha)


def select_backend(root,user,secret,backend,*,binary=None,notices=None,auxiliary=False,fault=None):
    if backend not in {'python','rust'}:raise APIError(422,'HOST_BACKEND_INVALID')
    from .hosting import load
    root=local_path(root,directory=True)
    with file_lock(root/'service-owner'):
        root,config,service=load(root,auxiliary=auxiliary)
        identity=service.auth.login(user,secret,'local-backend-selection')
        created=[];published=False
        try:
            actor=service.auth.authenticate(identity['token']);service.auth.admin(actor)
            private=root/'private';before=service.ledger.inventory()
            candidate_sha=None
            if backend=='rust':
                binary=local_path(binary);notices=local_path(notices);candidate_sha=file_hash(binary)
            if config.get('ledger_backend','python')==backend:
                if backend=='rust' and candidate_sha!=config.get('rust_worker_sha256'):raise Conflict('当前Rust版本不同，不自动更换')
                return config
            # Must be a complete maintenance package, not just a database copy.
            service.backup(kind='maintenance')
            if backend=='rust':
                old_sha=config.get('rust_worker_sha256')
                if old_sha is None and any((private/name).exists() for name in RUST_FILES):raise APIError(409,'UNOWNED_RUST_RESOURCE_EXISTS')
                if old_sha is not None:
                    if candidate_sha!=old_sha or file_hash(private/WORKER)!=old_sha:raise Conflict('已登记Rust资源版本不同')
                else:
                    for src,name in [(binary,WORKER),(notices,NOTICES)]:
                        with open(private/name,'xb') as target,open(src,'rb') as origin:
                            created.append(private/name);shutil.copyfileobj(origin,target);target.flush();os.fsync(target.fileno())
                if os.name!='nt' and auxiliary:(private/WORKER).chmod(0o700)
                if file_hash(private/WORKER)!=candidate_sha:raise APIError(503,'RUST_RESOURCE_COPY_FAILED')
                if fault:fault('worker_copied')
                candidate=RustLedger(private/'ledger.sqlite3',private/WORKER,auxiliary=auxiliary,expected_sha256=candidate_sha)
                config['rust_worker_sha256']=candidate_sha
            else:candidate=Ledger(private/'ledger.sqlite3')
            if candidate.inventory()!=before:raise APIError(503,'BACKEND_INVENTORY_CHANGED')
            config['ledger_backend']=backend
            if fault:fault('before_publish')
            publish_json(private/'service.json',config);published=True
            if fault:fault('after_publish')
            # Verify selection from persisted configuration before reporting success.
            _,observed,loaded=load(root,auxiliary=auxiliary)
            if observed!=config or loaded.ledger.inventory()!=before:raise APIError(503,'BACKEND_PUBLISH_UNVERIFIED')
            return config
        except BaseException:
            if not published:
                for path in created:path.unlink(missing_ok=True)
            raise
        finally:service.auth.logout(identity['token'])
