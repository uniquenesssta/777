"""Complete service bundles: consistent ledger snapshot, identities and TLS.

Restore always creates a new offline host; old sessions/passwords are revoked.
The original ledger-v1 backup and its validation stay unchanged.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import ssl
import uuid
import re

from quote_files.transactions import file_lock
from quote_ledger import Ledger
from quote_ledger.backup import Backups,hash_file,publish_json,read_json
from quote_ledger.paths import local_path
from quote_ledger.security import protect_directory
from .auth import Auth,username,password,verifier
from .protocol import APIError,fields


class ConfiguredBackups:
    """A missing backup target never silently changes the primary ledger."""
    def __init__(self,root,store_id,*,auxiliary=False):
        self.root=Path(root);self.store_id=store_id;self.auxiliary=auxiliary
        if not self.root.is_absolute():raise APIError(422,'BACKUP_PATH_INVALID')
    def manager(self):
        manager=Backups(self.root,auxiliary=self.auxiliary)
        if manager.status()['store_id']!=self.store_id:raise APIError(503,'BACKUP_STORE_IDENTITY_CONFLICT')
        return manager
    def status(self):return self.manager().status()
    def create_backup(self,*args,**kwargs):return self.manager().create_backup(*args,**kwargs)
    def run_due(self,*args,**kwargs):return self.manager().run_due(*args,**kwargs)
    def retain(self,*args,**kwargs):return self.manager().retain(*args,**kwargs)


FILES={'ledger.sqlite3','auth.sqlite3','tls-key.pem','tls-cert.pem','service.json'}


def accounts_cover_ledger(ledger,auth):
    with ledger.connection(readonly=True) as c:
        actors={row[0] for row in c.execute('SELECT owner_id FROM orders UNION SELECT author_id FROM notes UNION SELECT actor_id FROM requests UNION SELECT published_by FROM price_versions')}
    with auth.connection() as c:users={row[0] for row in c.execute('SELECT id FROM users')}
    if not actors<=users:raise APIError(503,'BACKUP_ACCOUNT_MAPPING_INCOMPLETE')


def manifest(folder,*,auxiliary=False):
    folder=local_path(folder,directory=True);value=read_json(folder/'manifest.json')
    fields(value,{'format','backup_id','ledger_id','files','inventory'})
    if value['format'] not in {'777-service-bundle-v1','777-service-bundle-v2','777-service-bundle-v3'} or str(uuid.UUID(value['backup_id']))!=value['backup_id']:
        raise APIError(422,'SERVICE_BACKUP_FORMAT_INVALID')
    names=set(value['files'])
    from .rust_ledger import RUST_FILES,WORKER,file_hash
    native=value['format']=='777-service-bundle-v3'
    basics=FILES|RUST_FILES if native else FILES
    outputs='outputs.sqlite3' in names
    if native and not basics<=names:raise APIError(422,'SERVICE_BACKUP_FORMAT_INVALID')
    if value['format']=='777-service-bundle-v1' and names!=FILES:raise APIError(422,'SERVICE_BACKUP_FORMAT_INVALID')
    if value['format']=='777-service-bundle-v2' and not outputs:raise APIError(422,'SERVICE_BACKUP_FORMAT_INVALID')
    allowed=basics|({'outputs.sqlite3'} if outputs else set())
    if not basics<=names or any(name not in allowed and (not outputs or not re.fullmatch(r'output-blobs/[0-9a-f-]{36}\.(xlsx|png)',name)) for name in names):raise APIError(422,'SERVICE_BACKUP_FORMAT_INVALID')
    roots=allowed|{'manifest.json'}|({'output-blobs'} if outputs else set())
    if outputs:
        blobs=local_path(folder/'output-blobs',directory=True)
        if {p.name for p in blobs.iterdir()}!={name.split('/')[1] for name in names if name.startswith('output-blobs/')}:raise APIError(422,'SERVICE_BACKUP_FILES_INVALID')
    if {p.name for p in folder.iterdir()}!=roots:raise APIError(422,'SERVICE_BACKUP_FILES_INVALID')
    for name,expected in value['files'].items():
        if hash_file(local_path(folder/name))!=expected:raise APIError(422,'SERVICE_BACKUP_HASH_INVALID')
    config=read_json(folder/'service.json')
    if native:
        if config.get('rust_worker_sha256')!=file_hash(folder/WORKER):raise APIError(422,'SERVICE_BACKUP_WORKER_INVALID')
    elif config.get('ledger_backend','python')!='python' or 'rust_worker_sha256' in config:raise APIError(422,'SERVICE_BACKUP_BACKEND_INVALID')
    from .backend import selected
    ledger=selected(folder,config,auxiliary=auxiliary);auth=Auth(folder/'auth.sqlite3')
    if ledger.inventory()!=value['inventory']:raise APIError(422,'SERVICE_BACKUP_INVENTORY_INVALID')
    accounts_cover_ledger(ledger,auth)
    if outputs:
        from .outputs import Outputs
        outputs=Outputs(folder/'outputs.sqlite3',value['ledger_id'],native=getattr(ledger,'native_formats',None))
        outputs.validate_ledger(ledger)
        with outputs.connection(readonly=True) as c:
            expected={'output-blobs/'+outputs.blob_path(row).name for row in c.execute('SELECT * FROM jobs WHERE blob_sha256 IS NOT NULL')}
        if expected!={name for name in names if name.startswith('output-blobs/')}:raise APIError(422,'SERVICE_BACKUP_OUTPUT_INDEX_INVALID')
    return value


def restore(folder,target,admin_name,new_password,*,auxiliary=False):
    value=manifest(folder,auxiliary=auxiliary);folder=Path(folder);target=local_path(target,directory=True,exists=False)
    if target.exists():raise FileExistsError('恢复只允许独立新主机目录')
    admin_name=username(admin_name);new_password=password(new_password)
    with Auth(folder/'auth.sqlite3').connection() as c:
        admin=c.execute("SELECT id FROM users WHERE username=? AND role='admin'",(admin_name,)).fetchone()
        if not admin:raise APIError(422,'RECOVERY_ADMIN_NOT_FOUND')
        admin_id=admin['id']
    if os.name!='nt' and not auxiliary:raise APIError(400,'WINDOWS_HOST_REQUIRED')
    target.mkdir(mode=0o700);private=target/'private';private.mkdir(mode=0o700)
    security=protect_directory(private) if os.name=='nt' else {'status':'auxiliary_no_native_security_claim'}
    if 'outputs.sqlite3' in value['files']:(private/'output-blobs').mkdir(mode=0o700)
    for name in value['files']:
        shutil.copyfile(local_path(folder/name),private/name)
        with open(private/name,'r+b') as stream:os.fsync(stream.fileno())
        if name=='rust-ledger-worker.exe' and os.name!='nt' and auxiliary:(private/name).chmod(0o700)
    config=read_json(private/'service.json')
    from .backend import selected
    ledger=selected(private,config,auxiliary=auxiliary);auth=Auth(private/'auth.sqlite3')
    with auth.connection() as c:
        c.execute('BEGIN IMMEDIATE')
        try:
            c.execute('DELETE FROM sessions')
            # Other users retain stable IDs but need explicit password reset
            # before enabling. A stale credential from a backup cannot log in.
            for row in c.execute('SELECT id FROM users').fetchall():
                salt=secrets.token_bytes(16)
                hashed=verifier(new_password,salt) if row['id']==admin_id else secrets.token_bytes(32)
                c.execute('UPDATE users SET enabled=?,salt=?,verifier=?,epoch=epoch+1 WHERE id=?',(int(row['id']==admin_id),salt,hashed,row['id']))
            c.execute('COMMIT')
        except BaseException:c.execute('ROLLBACK');raise
    config=read_json(private/'service.json');config['private_security']=security;config['maintenance']=True
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(str(private/'tls-cert.pem'),str(private/'tls-key.pem'))
    publish_json(private/'service.json',config)
    (target/'service-cert.pem').write_bytes((private/'tls-cert.pem').read_bytes())
    if ledger.inventory()!=value['inventory']:raise APIError(503,'RESTORED_LEDGER_MISMATCH')
    accounts_cover_ledger(ledger,auth)
    return ledger,auth


def bundle(service,ledger_entry,host_root,*,auxiliary=False):
    root=service.backups.root;parent=root/'service-bundles';index=root/'777-service-backups.json'
    with service.auth._lock,file_lock(index):
        if not index.exists():
            parent.mkdir(mode=0o700)  # Reject an existing unowned directory.
            publish_json(index,{'format':'777-service-backups-v1','ledger_id':service.ledger.inventory()['ledger_id'],'entries':[]})
        data=read_json(index)
        if data.get('format')!='777-service-backups-v1' or data['ledger_id']!=service.ledger.inventory()['ledger_id']:raise APIError(503,'SERVICE_BACKUP_INDEX_INVALID')
        identifier=ledger_entry['backup_id'];partial=parent/('.'+identifier+'.partial');final=parent/identifier
        partial.mkdir(mode=0o700)
        try:
            source=local_path(root/identifier/'ledger.sqlite3')
            if hash_file(source)!=ledger_entry['sha256']:raise APIError(503,'LEDGER_BACKUP_CHANGED')
            shutil.copyfile(source,partial/'ledger.sqlite3')
            with service.auth.connection() as origin,closing(sqlite3.connect(partial/'auth.sqlite3')) as destination:
                origin.backup(destination);destination.commit()
            for name in ('tls-key.pem','tls-cert.pem','service.json'):
                shutil.copyfile(local_path(Path(host_root)/'private'/name),partial/name)
            for name in FILES:
                with open(partial/name,'r+b') as stream:os.fsync(stream.fileno())
            inventory=Ledger(partial/'ledger.sqlite3').inventory()
            names=set(FILES);format='777-service-bundle-v1'
            config=read_json(partial/'service.json')
            if 'rust_worker_sha256' in config:
                from .rust_ledger import RUST_FILES
                for name in RUST_FILES:
                    shutil.copyfile(local_path(Path(host_root)/'private'/name),partial/name)
                    with open(partial/name,'r+b') as stream:os.fsync(stream.fileno())
                if os.name!='nt' and auxiliary:(partial/'rust-ledger-worker.exe').chmod(0o700)
                names|=RUST_FILES;format='777-service-bundle-v3'
            if service.outputs is not None:
                service.outputs.backup(partial);format='777-service-bundle-v3' if 'rust_worker_sha256' in config else '777-service-bundle-v2';names.add('outputs.sqlite3')
                names.update('output-blobs/'+p.name for p in (partial/'output-blobs').iterdir())
            value={'format':format,'backup_id':identifier,'ledger_id':inventory['ledger_id'],
                   'files':{name:hash_file(partial/name) for name in sorted(names)},'inventory':inventory}
            publish_json(partial/'manifest.json',value);manifest(partial,auxiliary=auxiliary)
            validation=parent/('.verify-'+identifier)
            try:
                with Auth(partial/'auth.sqlite3').connection() as c:admin=c.execute("SELECT username FROM users WHERE role='admin' ORDER BY username LIMIT 1").fetchone()[0]
                restored,auth=restore(partial,validation,admin,secrets.token_urlsafe(24),auxiliary=auxiliary)
                assert restored.inventory()==inventory
            finally:
                if validation.exists():shutil.rmtree(validation)
            os.rename(partial,final)
            entry={**ledger_entry,'service_bundle':str(final),'full_service_verified':True}
            data['entries'].append(entry);publish_json(index,data)
            return entry
        except BaseException:
            if partial.exists():shutil.rmtree(partial)
            raise


def retain(service):
    """Delete only separately indexed, verified bundles already retired by ledger policy."""
    root=service.backups.root;index=root/'777-service-backups.json'
    with file_lock(index):
        if not index.exists():return
        data=read_json(index);current={e['backup_id'] for e in service.backups.status()['backups']}
        removed=[e for e in data['entries'] if e['backup_id'] not in current]
        folders=[]
        for entry in removed:
            folder=root/'service-bundles'/entry['backup_id'];checked=manifest(folder,auxiliary=service.auxiliary)
            if checked['backup_id']!=entry['backup_id']:raise APIError(503,'SERVICE_BACKUP_INDEX_INVALID')
            folders.append(folder)
        data['entries']=[e for e in data['entries'] if e['backup_id'] in current];publish_json(index,data)
        for folder in folders:shutil.rmtree(folder)
