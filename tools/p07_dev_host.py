"""Persistent loopback-only development host; contains synthetic data only."""
import argparse, hashlib, json, os, secrets, shutil, signal, socket, sqlite3, subprocess, sys, threading
from contextlib import closing
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quote_service.auth import verifier
from quote_service.client import Client
from quote_service.protocol import APIError
from quote_service.journal import MemoryJournal
DEV = Path(os.environ['LOCALAPPDATA'])/'Quote777Development' if os.name=='nt' else ROOT/'reports/p07-development'
MARKER = {'format': '777-development-v1', 'production': False}
PORT = 18477

def wait_desktop(command, *, stopping=None):
    """Tauri owns Vite; this outer parent owns the independent service sibling."""
    stopping = stopping or threading.Event()
    process = subprocess.Popen(command,cwd=ROOT/'desktop',
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0,
        start_new_session=os.name!='nt')
    try:
        while process.poll() is None:
            try:cancelled=stopping.wait(.1)
            except KeyboardInterrupt:cancelled=True
            if cancelled:
                if os.name=='nt':process.send_signal(signal.CTRL_BREAK_EVENT)
                else:os.killpg(process.pid,signal.SIGINT)
                process.wait(timeout=20)
                return 130
        if process.returncode:raise RuntimeError(f'DEVELOPMENT_DESKTOP_EXIT_FAILED: {process.returncode}')
        return 0
    finally:
        if process.poll() is None:
            from p07_check_runner import stop_tree
            stop_tree(process)

def stop_host(process):
    if process.poll() is None:process.communicate(input=b'\n',timeout=50)
    else:process.communicate(timeout=50)
    if process.returncode:raise RuntimeError(f'DEVELOPMENT_HOST_EXIT_FAILED: {process.returncode}')

def command(args, password=None):
    cmd = [str(ROOT/'target/release'/('quote-host.exe' if os.name == 'nt' else 'quote-host')), *args]
    if os.name != 'nt': cmd.append('--auxiliary')
    if password is not None: cmd.append('--secret-stdin')
    r = subprocess.run(cmd, input=None if password is None else json.dumps({'password':password}).encode(), capture_output=True,timeout=90)
    if r.returncode: raise RuntimeError(r.stderr.decode('utf-8','replace')[-1500:])
    return json.loads(r.stdout.splitlines()[-1])

def prepare():
    # Refuse aliases and arbitrary existing directories before any mutation.
    for p in [DEV, *DEV.parents]:
        if p.exists() and (p.is_symlink() or getattr(p.stat(), 'st_file_attributes', 0) & 0x400):
            raise RuntimeError('DEVELOPMENT_DIRECTORY_REPARSE_POINT')
    if DEV.exists():
        if json.loads((DEV/'777-development.json').read_text(encoding='utf-8')) != MARKER:
            raise RuntimeError('UNOWNED_DEVELOPMENT_DIRECTORY')
    else:
        DEV.mkdir(parents=True)
        (DEV/'777-development.json').write_text(json.dumps(MARKER), encoding='utf-8')
    host = DEV/'host'
    binary = ROOT/'target/release'/('quote-ledger.exe' if os.name == 'nt' else 'quote-ledger')
    if not host.exists():
        command(['init','--root',str(host),'--backup-dir',str(DEV/'backups'),'--host','127.0.0.1','--host','localhost','--bind','127.0.0.1','--port',str(PORT),'--admin','admin','--worker',str(binary),'--notices',str(ROOT/'THIRD_PARTY_NOTICES.md')], secrets.token_urlsafe(24))
        # The requested short password is scoped to this owned development DB.
        # Normal account creation and production password validation remain unchanged.
        with closing(sqlite3.connect(host/'private/auth.sqlite3')) as c, c:
            salt = secrets.token_bytes(16)
            c.execute('UPDATE users SET salt=?,verifier=? WHERE username=?', (salt, verifier('123456',salt),'admin'))
    config = json.loads((host/'private/service.json').read_text(encoding='utf-8'))
    if config['bind'] != '127.0.0.1' or config['port'] != PORT or config['maintenance']:
        raise RuntimeError('DEVELOPMENT_HOST_CONFIG_CONFLICT')
    host_exe=ROOT/'target/release'/('quote-host.exe' if os.name=='nt' else 'quote-host')
    if config.get('rust_host_sha256')!=hashlib.sha256(host_exe.read_bytes()).hexdigest() or config.get('rust_worker_sha256')!=hashlib.sha256(binary.read_bytes()).hexdigest():
        print('更新本机开发服务资源（保留证书、账本和价格；先建立维护备份）…',flush=True)
        command(['select-host','--root',str(host),'--admin','admin','--backend','rust','--worker',str(binary),'--notices',str(ROOT/'THIRD_PARTY_NOTICES.md'),'--upgrade-resources'],'123456')
        config=json.loads((host/'private/service.json').read_text(encoding='utf-8'))

    profile = DEV/'desktop'; profile.mkdir(exist_ok=True)
    bootstrap = {'schema':'777-desktop-bootstrap-v1','delivery':'development','connection':{'url':f'https://127.0.0.1:{PORT}','certificate_pem':(host/'service-cert.pem').read_text(encoding='utf-8'),'certificate_sha256':config['certificate_sha256']},'username':'admin','password':'123456'}
    (profile/'bootstrap.json').write_text(json.dumps(bootstrap,ensure_ascii=True),encoding='utf-8')
    return host

def main():
    p=argparse.ArgumentParser();mode=p.add_mutually_exclusive_group();mode.add_argument('--frontend',action='store_true');mode.add_argument('--desktop',action='store_true');p.add_argument('--skip-build',action='store_true');p.add_argument('tauri_args',nargs=argparse.REMAINDER);args=p.parse_args()
    host_process=None;frontend=None;primary=None
    try:
        probe=socket.socket()
        try: probe.bind(('127.0.0.1',PORT))
        finally: probe.close()
        if not args.skip_build:
            print('准备本机开发服务（单任务增量构建）…',flush=True)
            subprocess.run(['cargo','build','--locked','--release','-p','quote-host','-p','quote-ledger','-j','1'],cwd=ROOT,check=True)
        host=prepare()
        cmd=[str(ROOT/'target/release'/('quote-host.exe' if os.name=='nt' else 'quote-host')),'run','--root',str(host),'--isolated-test','--test-shutdown-stdin']
        if os.name!='nt':cmd.append('--auxiliary')
        host_process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=None,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=="nt" else 0,start_new_session=os.name!="nt")
        ready=json.loads(host_process.stdout.readline())
        if ready.get('status')!='ready':raise RuntimeError('DEVELOPMENT_HOST_NOT_READY')
        cfg=json.loads((host/'private/service.json').read_text(encoding='utf-8'))
        client=Client({'schema':'777-service-client-v1','url':f'https://127.0.0.1:{PORT}','certificate':str(host/'service-cert.pem'),'certificate_sha256':cfg['certificate_sha256'],'username':'admin'})
        client.login('admin','123456')
        try:
            try:client.request('GET','/v1/prices')
            except APIError as e:
                if e.code!='PRICES_NOT_PUBLISHED':raise
                client.mutate('/v1/prices',{'expected_price_version_id':None,'prices':{'price_version_id':'development-v1','items':[{'product_id':'户外写真','sale':'20','cost':'10','k':'1','single':False},{'product_id':'PVC 硬板','sale':'85','cost':'45','k':'1','single':False},{'product_id':'安装服务','sale':'100','cost':'50','k':'1','single':True}]}},MemoryJournal())
        finally:client.logout()
        print(f'本机开发服务已就绪：https://127.0.0.1:{PORT}；地址和证书保留，桌面端自动连接。',flush=True)
        if args.desktop:
            stopping=threading.Event()
            if not sys.stdin.isatty():
                # The Node launcher closes/writes its private pipe on cancellation.
                def control():
                    os.read(sys.stdin.fileno(),1);stopping.set()
                threading.Thread(target=control,daemon=True).start()
            extra=args.tauri_args[1:] if args.tauri_args[:1]==['--'] else args.tauri_args
            return wait_desktop([os.environ.get('QUOTE777_NODE') or shutil.which('node'),str(ROOT/'desktop/node_modules/@tauri-apps/cli/tauri.js'),'dev',*extra],stopping=stopping)
        elif args.frontend:
            frontend=subprocess.Popen([shutil.which('node'),str(ROOT/'desktop/node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port','29346','--strictPort'],cwd=ROOT/'desktop')
            if frontend.wait():raise RuntimeError("DEVELOPMENT_FRONTEND_EXIT_FAILED")
        else:input('关闭桌面后按回车停止服务（开发数据和证书保留）：')
    except KeyboardInterrupt:
        print('开发启动已中止，正在关闭本轮服务…',flush=True)
        return 130
    except BaseException as error:
        primary=error;raise
    finally:
        if frontend and frontend.poll() is None:frontend.terminate();frontend.wait(timeout=15)
        if host_process:
            try:stop_host(host_process)
            except Exception as error:
                if primary:primary.add_note('服务收尾同时失败：'+str(error))
                else:raise
if __name__=='__main__':raise SystemExit(main())
