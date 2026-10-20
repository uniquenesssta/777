"""Owned temporary Rust host/client for P07 checks; never a production service adapter."""
import argparse,json,os,queue,secrets,subprocess,sys,tempfile,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from native_host_fixture import Hosted
from quote_service.journal import MemoryJournal
from quote_core import QuoteSnapshot,NormalLine,DraftDetails
CLIENT=Path(os.environ.get('P07_DESKTOP_BINARY',str(ROOT/'target/release'/('quote-desktop.exe' if os.name=='nt' else 'quote-desktop'))))
class Scenario:
    def __init__(self,*,password=None):
        self.host=Hosted(password=password);self.bridge=None;self.lock=threading.RLock();self.profile=self.host.root/'desktop';self.profile.mkdir();(self.profile/'777-isolated-profile.json').write_text('{"production":false}',encoding='utf-8')
        manager=self.host.client('manager')
        prices={'price_version_id':'2026.10.13','items':[{'product_id':'户外写真','sale':'20','cost':'10','k':'1','single':False},{'product_id':'PVC 硬板','sale':'85','cost':'45','k':'1','single':False},{'product_id':'安装服务','sale':'100','cost':'50','k':'1','single':True}]}
        manager.mutate('/v1/prices',{'prices':prices,'expected_price_version_id':'fixture-v1'},MemoryJournal())
        one=self.host.client('sales-one');two=self.host.client('sales-two')
        for i in range(25):
            (one if i<23 else two).submit(QuoteSnapshot('2026.10.13',(NormalLine('安装服务','1'),)),DraftDetails('客户'+str(i),f'000{i:02d}','wx'),MemoryJournal())
        self.public=self.host.root/'public';self.public.mkdir()
        with self.host.service.auth.connection() as c:c.execute('UPDATE preferences SET export_dir=?,image_dir=?,revision=revision+1 WHERE id=1',(str(self.public),str(self.public)))
        self.start_bridge()
    def start_bridge(self):
        self.bridge=subprocess.Popen([str(CLIENT),'--verification-bridge','--profile',str(self.profile)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    def stop_bridge(self):
        if self.bridge:
            _,err=self.bridge.communicate(timeout=30)
            if self.bridge.returncode:raise RuntimeError('DESKTOP_VERIFICATION_PROCESS_FAILED:'+err.decode('utf-8','replace')[-1000:])
            self.bridge=None
    def connection(self):
        return {'url':f'https://127.0.0.1:{self.host.port}','certificate_pem':(self.host.host_root/'service-cert.pem').read_text(encoding='utf-8'),'certificate_sha256':self.host.config['certificate_sha256']}
    def fixture(self):return {'connection':self.connection(),'username':'manager','password':self.host.password,'profile':str(self.profile)}
    def call(self,action):
        with self.lock:
            self.bridge.stdin.write(json.dumps(action,ensure_ascii=True).encode()+b'\n');self.bridge.stdin.flush()
            result=queue.Queue();p=self.bridge
            threading.Thread(target=lambda:result.put(p.stdout.readline()),daemon=True).start()
            try:line=result.get(timeout=40)
            except queue.Empty:raise RuntimeError('DESKTOP_VERIFICATION_TIMEOUT') from None
            if not line:raise RuntimeError('DESKTOP_VERIFICATION_EXITED')
            return json.loads(line)
    def close(self):
        try:self.stop_bridge()
        finally:self.host.close()
class Handler(BaseHTTPRequestHandler):
    scenario=None
    def log_message(self,*args):pass
    def send_json(self,value,status=200):
        data=json.dumps(value,ensure_ascii=True).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Access-Control-Allow-Origin','http://127.0.0.1:29346');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_OPTIONS(self):
        self.send_response(204);self.send_header('Access-Control-Allow-Origin','http://127.0.0.1:29346');self.send_header('Access-Control-Allow-Headers','Content-Type');self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS');self.end_headers()
    def do_GET(self):
        if self.path=='/font.ttf' and os.environ.get('P06_CI_FONT_FILE'):
            data=Path(os.environ['P06_CI_FONT_FILE']).read_bytes();self.send_response(200);self.send_header('Content-Type','font/ttf');self.send_header('Access-Control-Allow-Origin','http://127.0.0.1:29346');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
        if self.path=='/health':return self.send_json({'status':'ready'})
        if self.path=='/fixture' and self.scenario:return self.send_json(self.scenario.fixture())
        self.send_json({'error':'NOT_FOUND'},404)
    def do_POST(self):
        try:
            length=int(self.headers.get('Content-Length','0'));assert 0<=length<=1024*1024
            data=json.loads(self.rfile.read(length) or b'{}')
            if self.path=='/cleanup':
                if Handler.scenario:Handler.scenario.close();Handler.scenario=None
                return self.send_json({'sandbox_cleaned':True})
            if self.path=='/reset':
                if Handler.scenario:Handler.scenario.close()
                Handler.scenario=Scenario();return self.send_json(Handler.scenario.fixture())
            if self.path=='/action' and self.scenario:return self.send_json(self.scenario.call(data))
            if self.path=='/fault-after-commit' and self.scenario:self.scenario.host.fault.write_text('after_commit',encoding='utf-8');return self.send_json({'ok':True})
            if self.path=='/restart' and self.scenario:self.scenario.host.restart();return self.send_json({'ok':True})
            self.send_json({'error':'NOT_FOUND'},404)
        except Exception as e:self.send_json({'error':type(e).__name__},500)
def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=18777);a=p.parse_args();server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler)
    try:server.serve_forever()
    finally:
        server.server_close()
        if Handler.scenario:Handler.scenario.close()
if __name__=='__main__':main()
