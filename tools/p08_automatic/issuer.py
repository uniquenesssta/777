"""Read-only status and one-time owner upgrade preparation, separate from data sources."""
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import uuid

class Issuer:
    def __init__(self,owner):
        self.owner=owner
        self.state=owner.dev.DEV/'issuer.bin'
        self.cache=None
        self.checked=0
        self.location=owner.dev.DEV/'issuer-kit.json'

    def native(self,args,timeout=180):
        if os.name!='nt':raise RuntimeError('WINDOWS_PACKAGING_REQUIRED')
        native=self.owner.dev.ROOT/'target/release/quote-host.exe'
        p=subprocess.run([str(native),*args],capture_output=True,text=True,encoding='utf-8',timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
        if p.returncode:
            try:code=json.loads(p.stderr)['error']
            except (ValueError,KeyError):code='AUTOMATIC_PREPARATION_FAILED'
            raise RuntimeError(code)
        return json.loads(p.stdout)

    def status(self,refresh=False):
        if not refresh and self.cache is not None and time.monotonic()-self.checked<10:return self.cache
        if os.name!='nt':return dict(ready=False,phase='windows_required',interfaces=[])
        addresses=[]
        try:
            for address in socket.gethostbyname_ex(socket.gethostname())[2]:
                ip=ipaddress.ip_address(address)
                if ip.version==4 and not ip.is_loopback and not ip.is_unspecified:addresses.append(address)
        except OSError:pass
        try:result=self.native(['automatic-issuer-status','--state',str(self.state)])
        except (RuntimeError,OSError,subprocess.TimeoutExpired):result=dict(ready=False,phase='upgrade_required')
        # Only public identity and readiness cross the control bridge.
        self.cache={k:result.get(k) for k in ['ready','phase','site_id','ledger_id']}
        self.cache['interfaces']=sorted(set(addresses))
        self.checked=time.monotonic()
        return self.cache

    def prepare(self,peer,restart=False):
        from p07_developer import replace_json
        status=self.status(refresh=True)
        if status['ready']:raise RuntimeError('ISSUER_ALREADY_READY')
        peers=status['interfaces']
        if peer is None and len(peers)==1:peer=peers[0]
        if peer not in peers:raise RuntimeError('ISSUER_INTERFACE_SELECTION_REQUIRED')
        if status['phase']=='pending' and not restart and self.location.exists():return self.open_kit()
        if restart and self.state.exists():
            # Preserve the old protected attempt; never overwrite an established binding.
            os.replace(self.state,self.state.with_name('issuer-previous-'+uuid.uuid4().hex+'.bin'))
        directory=self.owner.dev.DEV/('Quote777Upgrade-'+uuid.uuid4().hex[:10])
        self.native(['automatic-prepare','--state',str(self.state),'--output',str(directory),'--peer',peer,'--notices',str(self.owner.dev.ROOT/'THIRD_PARTY_NOTICES.md')])
        replace_json(self.location,dict(directory=str(directory)))
        os.startfile(str(directory))
        return self.status(refresh=True)

    def open_kit(self):
        path=Path(json.loads(self.location.read_text(encoding='utf-8'))['directory'])
        if path.parent!=self.owner.dev.DEV or not path.is_dir():raise RuntimeError('ISSUER_KIT_UNAVAILABLE')
        os.startfile(str(path))
        return self.status(refresh=True)

    def connect(self):
        self.native(['automatic-connect','--state',str(self.state)])
        return self.status(refresh=True)
