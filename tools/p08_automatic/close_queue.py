"""Durable close-only compensation for abandoned grants; never creates replacement identities."""
import json
import os
from pathlib import Path
import threading
import time
import uuid
import p07_diagnostics as diagnostics
from operational_logs.metadata import valid_id

class CloseQueue:
    def __init__(self, issuer, directory):
        self.issuer, self.directory = issuer, Path(directory)
        self.file=self.directory/'close-queue.json'
        self.lock=threading.Lock()
        self.stop=threading.Event()
        self.thread=None
        self.rows={}
        if self.file.exists():
            if self.file.stat().st_size>262144:raise RuntimeError('PACKAGE_CLOSE_QUEUE_INVALID')
            value=json.loads(self.file.read_text(encoding='utf-8'))
            if value.get('format')!='777-package-close-queue-v1':raise RuntimeError('PACKAGE_CLOSE_QUEUE_INVALID')
            for row in value['pending']:
                key=row['package_id']
                if str(uuid.UUID(key))!=key or not valid_id(row['execution_id']):raise RuntimeError('PACKAGE_CLOSE_QUEUE_INVALID')
                self.rows[key]=row
        if len(self.rows)>512:raise RuntimeError('PACKAGE_CLOSE_QUEUE_INVALID')

    def save(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        temporary=self.file.with_suffix('.partial')
        try:
            with temporary.open('w',encoding='utf-8') as stream:
                json.dump(dict(format='777-package-close-queue-v1',pending=list(self.rows.values())),stream)
                stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,self.file)
        finally:temporary.unlink(missing_ok=True)

    def enqueue(self,key):
        if str(uuid.UUID(key))!=key:raise RuntimeError('PACKAGE_CLOSE_QUEUE_INVALID')
        with self.lock:
            if key not in self.rows:
                if len(self.rows)>=512:raise RuntimeError('PACKAGE_CLOSE_QUEUE_FULL')
                execution=os.environ.get('QUOTE777_EXECUTION_ID','')
                self.rows[key]=dict(package_id=key,execution_id=execution if valid_id(execution) else key,attempt=0,next=0)
                self.save()
        diagnostics.event('package.close.queued',package_id=key)

    def once(self,now=None):
        now=time.time() if now is None else now
        with self.lock:
            row=next((dict(r) for r in self.rows.values() if r['next']<=now),None)
        if row is None:return
        key=row['package_id'];candidate=self.directory/(key+'.bin')
        try:
            if candidate.is_symlink() or self.directory.is_symlink():raise RuntimeError('PACKAGE_CLOSE_PATH_INVALID')
            if candidate.exists():
                try:self.issuer.native(['automatic-close','--state',str(self.issuer.state),'--candidate',str(candidate)],timeout=10)
                except RuntimeError as error:
                    if str(error)!='NOT_FOUND':raise
            with self.lock:
                self.rows.pop(key,None);self.save()
            diagnostics.event('package.close.completed',package_id=key,origin_execution_id=row['execution_id'])
        except Exception as error:
            diagnostics.failure('package.close',error)
            with self.lock:
                r=self.rows.get(key)
                if r is not None:
                    r['attempt']=min(9,r['attempt']+1)
                    r['next']=now+min(300,2**r['attempt'])
                    self.save()
            diagnostics.event('package.close.pending',package_id=key,retry=True,origin_execution_id=row['execution_id'])

    def start(self):
        def loop():
            while not self.stop.is_set():
                try:self.once()
                except Exception as error:diagnostics.failure('package.close.queue',error)
                self.stop.wait(2)
        self.thread=threading.Thread(target=loop,name='package-close',daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=12)
