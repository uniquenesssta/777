"""A separate Rust TLS process, never a Python/ASGI server in disguise."""
import json,os,queue,secrets,socket,subprocess,tempfile,threading,time
from pathlib import Path
from quote_service.client import Client
from quote_service.hosting import load
ROOT=Path(__file__).resolve().parents[1]
BINARY=ROOT/'target/release'/('quote-host.exe' if os.name=='nt' else 'quote-host')
WORKER=ROOT/'target/release'/('quote-ledger.exe' if os.name=='nt' else 'quote-ledger')
AUXILIARY=os.name!='nt'
def command(name,*,root,secret=None,**options):
    args=[str(BINARY),name,'--root',str(root)]
    if AUXILIARY:args.append('--auxiliary')
    for k,v in options.items():
        flag='--'+k.replace('_','-')
        if isinstance(v,bool):
            if v:args.append(flag)
        elif isinstance(v,(list,tuple)):
            for value in v:args.extend([flag,str(value)])
        elif v is not None:args.extend([flag,str(v)])
    if secret is not None:args.append('--secret-stdin')
    p=subprocess.run(args,input=None if secret is None else json.dumps({'password':secret}).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
    lines=p.stdout.splitlines()
    if p.returncode:raise RuntimeError('native command failed: '+p.stderr.decode('utf-8','replace')[-500:])
    return json.loads(lines[-1])
def backup_pair(host, entry):
    return Path(host.config['backup_dir']) / (host.config['ledger_id'] + '-' + entry['business_date'] + '-' + entry['backup_id'])

def restore_data_backup(host, entry, target, *, user='recovered-manager', password='restored-password-123'):
    return command('restore-data', root=target, package=backup_pair(host,entry)/'data.qbackup', backup_dir=target.with_name(target.name+'-backups'), host=['127.0.0.1','localhost'], bind='127.0.0.1', port=host.port, admin=user, worker=WORKER, notices=ROOT/'THIRD_PARTY_NOTICES.md', secret=password)

class Hosted:
    def __init__(self,*,font=None,bootstrap=True):
        self.temp=tempfile.TemporaryDirectory(prefix='777-p06-native-host-');self.root=Path(self.temp.name);self.host_root=self.root/'host';self.password=secrets.token_urlsafe(24);self.font=font or os.environ.get('P06_CI_FONT_FILE');self.process=None
        try:
            sock=socket.socket();sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1];sock.close()
            command('init',root=self.host_root,secret=self.password,backup_dir=self.root/'backups',host=['127.0.0.1','localhost'],port=self.port,worker=WORKER,notices=ROOT/'THIRD_PARTY_NOTICES.md')
            self.config=json.loads((self.host_root/'private/service.json').read_bytes());self.fault=self.host_root/'private/test-fault.txt'
            self.start()
            if bootstrap:
                admin=self.client('manager');admin.request('POST','/v1/accounts',{'username':'sales-one','password':self.password,'role':'sales'});admin.request('POST','/v1/accounts',{'username':'sales-two','password':self.password,'role':'sales'})
                import uuid
                admin.request('POST','/v1/prices',{'request_id':str(uuid.uuid4()),'expected_price_version_id':None,'prices':{'price_version_id':'fixture-v1','items':[{'product_id':'单件','sale':'10','cost':'4','k':'1','single':True}]}})
            _,_,self.service=load(self.host_root,auxiliary=AUXILIARY)
            login=self.service.auth.login('manager',self.password,'independent-fixture-reader');self.admin=self.service.auth.authenticate(login['token']);self.service.auth.logout(login['token'])
        except BaseException:
            self.close()
            raise
    def start(self):
        args=[str(BINARY),'run','--root',str(self.host_root),'--isolated-test','--test-shutdown-stdin','--test-fault-file',str(self.fault)]
        if AUXILIARY:args.append('--auxiliary')
        if self.font:args.extend(['--test-font-file',str(self.font)])
        self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        results=queue.Queue()
        def ready():results.put(self.process.stdout.readline())
        threading.Thread(target=ready,daemon=True).start()
        try:line=results.get(timeout=15)
        except queue.Empty:self.process.kill();self.process.wait(10);raise RuntimeError('native HTTPS readiness timed out')
        if not line or json.loads(line).get('status')!='ready':raise RuntimeError('native HTTPS failed: '+self.process.stderr.read().decode()[-500:])
        self.ready=json.loads(line)
    def client(self,user='sales-one',*,login=True):
        c=Client({'schema':'777-service-client-v1','url':f'https://127.0.0.1:{self.port}','certificate':str(self.host_root/'service-cert.pem'),'certificate_sha256':self.config['certificate_sha256'],'username':user})
        if login:
            deadline=time.monotonic()+5
            while True:
                try:c.login(user,self.password);break
                except Exception:
                    if time.monotonic()>deadline:raise
                    time.sleep(.02)
        return c
    def stop(self):
        p=self.process
        if p is None:return
        # communicate owns writing and closing stdin, including the Windows
        # EINVAL race when a fault-injected child has already closed its pipe.
        try:out,err=p.communicate(input=b'\n',timeout=50)
        except subprocess.TimeoutExpired:raise RuntimeError('native service has not stopped; sandbox retained')
        if p.returncode not in (0,17,18):raise RuntimeError('native service exit: '+err.decode('utf-8','replace')[-500:])
        self.process=None
    def restart(self):self.stop();self.fault.unlink(missing_ok=True);self.start()
    def close(self):self.stop();self.temp.cleanup()
