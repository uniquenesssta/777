"""Consistent SQLite snapshots, manifest-limited retention, independent restores.

The manager is a service-side adapter. P05-02 owns its real scheduled runner and
identity; creating a manager does not install a service or start a timer.
"""
from datetime import datetime, timedelta, timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
import uuid

from quote_files.transactions import file_lock
from .paths import LedgerError, InvalidDatabase, local_path
from .security import protect_directory
from .store import Ledger, encoded, inventory


def hash_file(path):
    result=hashlib.sha256()
    with open(path,'rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):result.update(block)
    return result.hexdigest()


def read_json(path):
    path=local_path(path)
    raw=path.read_bytes()
    if len(raw)>1024*1024:raise LedgerError('备份清单过大')
    return json.loads(raw.decode('utf-8'))


def publish_json(path,value):
    # Only manager-owned status/list manifests use replace. Backup IDs never do.
    local_path(path,exists=False)
    temp=path.with_name('.'+path.name+'.'+str(uuid.uuid4())+'.tmp')
    try:
        with open(temp,'x',encoding='utf-8') as stream:
            stream.write(encoded(value));stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        try:temp.unlink()
        except FileNotFoundError:pass


class Backups:
    def __init__(self,root,*,auxiliary=False):
        self.root=local_path(root,directory=True)
        if os.name=='nt' and auxiliary:raise LedgerError('Windows不能关闭备份属性/ACL保护')
        if os.name!='nt' and not auxiliary:raise LedgerError('实际备份保护需要Windows')
        self.auxiliary=auxiliary
        self.index=self.root/'777-backups.json'
        data=read_json(self.index)
        if data.get('format')!='777-backups-v1' or not isinstance(data.get('backups'),list):raise LedgerError('不是本应用备份目录')

    @classmethod
    def create(cls,root,*,auxiliary=False):
        if os.name=='nt' and auxiliary:raise LedgerError('Windows不能关闭备份属性/ACL保护')
        if os.name!='nt' and not auxiliary:raise LedgerError('实际备份保护需要Windows')
        root=local_path(root,directory=True,exists=False)
        root.mkdir(mode=0o700)  # Never adopt/alter an arbitrary existing folder.
        if os.name=='nt':security=protect_directory(root)
        elif auxiliary:security={'status':'auxiliary_no_Windows_attributes_or_ACL_claim'}
        else:raise LedgerError('实际备份保护需要Windows')
        publish_json(root/'777-backups.json',{'format':'777-backups-v1','store_id':str(uuid.uuid4()),'security':security,'backups':[],'last_success':None,'last_error':None})
        return cls(root,auxiliary=auxiliary)

    def status(self):return read_json(self.index)

    def create_backup(self,ledger,*,kind='rolling',clock=None,timeout=30):
        if kind not in {'rolling','daily','maintenance'}:raise LedgerError('未知备份类型')
        local_path(self.root,directory=True)
        with file_lock(self.index):
            data=self.status();when=clock or datetime.now(timezone.utc)
            if when.tzinfo is None:raise LedgerError('备份时间需要时区')
            backup_id=str(uuid.uuid4());partial=self.root/('.'+backup_id+'.partial');final=self.root/backup_id
            partial.mkdir(mode=0o700)
            try:
                target=partial/'ledger.sqlite3'
                with ledger.connection(readonly=True) as source:
                    destination=sqlite3.connect(target,isolation_level=None)
                    try:
                        deadline=time.monotonic()+timeout
                        def progress(status,remaining,total):
                            if time.monotonic()>deadline:raise LedgerError('备份快照超时；原账本不变')
                        source.backup(destination,pages=128,progress=progress,sleep=.01)
                        destination.execute('PRAGMA journal_mode=DELETE')
                        destination.row_factory=sqlite3.Row
                        checked=inventory(destination)
                    finally:destination.close()
                # Windows _commit/FlushFileBuffers requires write access.
                # r+b opens the owned snapshot without creating/truncating it.
                with open(target,'r+b') as stream:os.fsync(stream.fileno())
                manifest={'format':'777-ledger-backup-v1','backup_id':backup_id,'kind':kind,'created_at':when.isoformat(),'sha256':hash_file(target),'inventory':checked,'attachments':[],'attachment_scope':'P05-01 has no persisted attachments; P05-04 owns attachment inventory/copy.'}
                with open(partial/'manifest.json','x',encoding='utf-8') as stream:
                    stream.write(encoded(manifest));stream.flush();os.fsync(stream.fileno())
                os.rename(partial,final)
                # Publish success only after an actual independent restore.
                validation=self.root/('.verify-'+backup_id+'.sqlite3')
                try:restored=restore_backup(final,validation);assert restored.inventory()==checked
                finally:
                    for path in (validation,Path(str(validation)+'-wal'),Path(str(validation)+'-shm')):
                        try:path.unlink()
                        except FileNotFoundError:pass
                entry={'backup_id':backup_id,'kind':kind,'created_at':when.isoformat(),'sha256':manifest['sha256'],'verified_restore':True}
                data['backups'].append(entry);data['last_success']=entry;data['last_error']=None
                publish_json(self.index,data)
                return entry
            except BaseException as exc:
                data['last_error']={'at':when.isoformat(),'reason':type(exc).__name__+': '+str(exc)}
                try:publish_json(self.index,data)
                except Exception:pass
                if partial.exists():shutil.rmtree(partial)
                raise

    def run_due(self,ledger,*,now,interval_minutes=30,daily_hour=2):
        if not 1<=interval_minutes<=1440 or not 0<=daily_hour<=23 or now.tzinfo is None:raise LedgerError('备份计划无效')
        with file_lock(self.root/'scheduler'):
            data=self.status();revision=ledger.inventory()['revision']
            daily=[b for b in data['backups'] if b['kind']=='daily' and datetime.fromisoformat(b['created_at']).astimezone(now.tzinfo).date()==now.date()]
            if now.hour>=daily_hour and not daily:return self.create_backup(ledger,kind='daily',clock=now)
            latest=data['last_success']
            if latest:
                manifest=read_json(self.root/latest['backup_id']/'manifest.json')
                if manifest['inventory']['revision']==revision:return None
                if now-datetime.fromisoformat(latest['created_at'])<timedelta(minutes=interval_minutes):return None
            return self.create_backup(ledger,clock=now)

    def retain(self,*,rolling=48,daily=30):
        if type(rolling) is not int or type(daily) is not int or min(rolling,daily)<1:raise LedgerError('必须保留最近成功备份')
        with file_lock(self.index):
            data=self.status();keep=set()
            for kind,limit in (('rolling',rolling),('daily',daily)):
                keep.update(b['backup_id'] for b in data['backups'] if b['kind']==kind and b['backup_id'] in [x['backup_id'] for x in data['backups'] if x['kind']==kind][-limit:])
            keep.update(b['backup_id'] for b in data['backups'] if b['kind']=='maintenance')
            if data['last_success']:keep.add(data['last_success']['backup_id'])
            discarded=[b for b in data['backups'] if b['backup_id'] not in keep]
            # Validate all candidates before any deletion; unknown files are untouched.
            for b in discarded:
                identifier=uuid.UUID(b['backup_id'])
                if str(identifier)!=b['backup_id']:raise LedgerError('备份ID损坏')
                folder=local_path(self.root/b['backup_id'],directory=True)
                manifest=read_json(folder/'manifest.json')
                if manifest['backup_id']!=b['backup_id'] or hash_file(local_path(folder/'ledger.sqlite3'))!=b['sha256'] or {p.name for p in folder.iterdir()}!={'manifest.json','ledger.sqlite3'}:raise LedgerError('过期包内容异常，保留原件')
            data['backups']=[b for b in data['backups'] if b['backup_id'] in keep]
            publish_json(self.index,data)
            for b in discarded:shutil.rmtree(self.root/b['backup_id'])
            return [b['backup_id'] for b in discarded]


def restore_backup(folder,target):
    folder=local_path(folder,directory=True);target=local_path(target,exists=False)
    if target.exists():raise LedgerError('恢复只能写入独立新文件，禁止覆盖现有账本')
    for sidecar in (Path(str(target)+'-wal'),Path(str(target)+'-shm')):
        local_path(sidecar,exists=False)
        if sidecar.exists():raise LedgerError('恢复目标已有SQLite附属文件，原件保留')
    manifest=read_json(folder/'manifest.json');source=local_path(folder/'ledger.sqlite3')
    if manifest.get('format')!='777-ledger-backup-v1' or hash_file(source)!=manifest.get('sha256'):raise InvalidDatabase('备份清单或哈希不一致')
    with Ledger(source).connection(readonly=True) as checked:
        if inventory(checked)!=manifest['inventory']:raise InvalidDatabase('备份核对清单不一致')
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as origin, closing(sqlite3.connect(target)) as destination:
            origin.backup(destination,pages=128)
            destination.commit()
            destination.execute('PRAGMA journal_mode=WAL')
            destination.execute('PRAGMA synchronous=FULL')
        restored=Ledger(target)
        if restored.inventory()!=manifest['inventory'] or hash_file(source)!=manifest['sha256']:raise InvalidDatabase('独立恢复核对失败')
        return restored
    except BaseException:
        try:target.unlink()
        except FileNotFoundError:pass
        raise
