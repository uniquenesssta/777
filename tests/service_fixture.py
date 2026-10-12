"""Isolated real TCP/TLS host fixture. No real share, E drive or credential."""
import hashlib
import os
from pathlib import Path
import secrets
import socket
import tempfile
import threading
import time
import uuid

from quote_core import PriceSnapshot,PriceItem
from quote_service.hosting import initialize,load,server
from quote_service.client import Client


class Hosted:
    def __init__(self):
        self.temp=tempfile.TemporaryDirectory(prefix='777-p05-service-');self.root=Path(self.temp.name)
        self.password=secrets.token_urlsafe(24)
        self.config=initialize(self.root/'host',self.root/'backups','manager',self.password,
                               hosts=['127.0.0.1','localhost'],auxiliary=os.name!='nt')
        _,_,self.service=load(self.root/'host',auxiliary=os.name!='nt')
        identity=self.service.auth.login('manager',self.password,'fixture');self.admin=self.service.auth.authenticate(identity['token'])
        self.service.auth.create_account(self.admin,'sales-one',self.password,'sales')
        self.service.auth.create_account(self.admin,'sales-two',self.password,'sales')
        self.service.ledger.publish_prices(str(uuid.uuid4()),self.admin,PriceSnapshot('fixture-v1',(PriceItem('单件','10','4','1',True),)))
        self.sock=socket.socket();self.sock.bind(('127.0.0.1',0));self.port=self.sock.getsockname()[1]
        self.server=server(self.service,self.root/'host/private/tls-cert.pem',self.root/'host/private/tls-key.pem')
        self.errors=[]
        def run():
            try:self.server.run(sockets=[self.sock])
            except BaseException as exc:self.errors.append(exc)
        self.thread=threading.Thread(target=run,name='777-test-https',daemon=True);self.thread.start()
        deadline=time.monotonic()+10
        while not self.server.started:
            if self.errors or not self.thread.is_alive() or time.monotonic()>deadline:raise RuntimeError('isolated TLS startup failed')
            time.sleep(.01)

    def client(self,user='sales-one'):
        client=Client({'schema':'777-service-client-v1','url':f'https://127.0.0.1:{self.port}',
                       'certificate':str(self.root/'host/service-cert.pem'),'certificate_sha256':self.config['certificate_sha256'],'username':user})
        client.login(user,self.password)
        return client

    def close(self):
        self.server.should_exit=True;self.thread.join(45)
        if self.thread.is_alive():raise RuntimeError('TLS fixture has not stopped; sandbox retained')
        if self.errors:raise self.errors[0]
        self.sock.close();self.temp.cleanup()
