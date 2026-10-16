"""P07-02 isolated device identity and native no-login evidence; never touches production."""
import argparse, hashlib, json, os, platform, queue, shutil, socket, subprocess, sys, threading, traceback
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(ROOT/'tests')]
from native_host_fixture import Hosted,command
from p01_validation import new_output
from p07_check_runner import Progress,preflight,stop_tree
EXT='.exe' if os.name=='nt' else ''

class Bridge:
    def __init__(self,binary,profile):
        self.p=subprocess.Popen([str(binary),'--verification-bridge','--profile',str(profile)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    def call(self,action,**data):
        self.p.stdin.write(json.dumps({'action':action,**data}).encode()+b'\n');self.p.stdin.flush();q=queue.Queue()
        threading.Thread(target=lambda:q.put(self.p.stdout.readline()),daemon=True).start()
        raw=q.get(timeout=45)
        if not raw:raise RuntimeError('DEVICE_BRIDGE_EXITED')
        return json.loads(raw)
    def ok(self,action,**data):
        value=self.call(action,**data)
        if 'error' in value:raise RuntimeError(value['error']['code'])
        return value['ok']
    def close(self):
        self.p.communicate(timeout=30)
        if self.p.returncode:raise RuntimeError('DEVICE_BRIDGE_NONZERO')

def enable(h):
    h.stop();command('enable-devices',root=h.host_root,admin='manager',secret=h.password);h.start()

def configure(h,kind,folder):
    profile=h.root/folder;profile.mkdir();(profile/'777-isolated-profile.json').write_text('{"production":false}',encoding='utf-8')
    admin=h.client('manager');name='manager' if kind=='manager' else 'sales-one'
    account=next(a for a in admin.request('GET','/v1/accounts')['accounts'] if a['username']==name)
    grant=admin.request('POST','/v1/device-grants',{'subject':account['id'],'delivery':kind,'ttl_seconds':600})
    value={'schema':'777-desktop-bootstrap-v1','delivery':kind,'connection':{'url':f'https://127.0.0.1:{h.port}','certificate_pem':(h.host_root/'service-cert.pem').read_text(encoding='utf-8'),'certificate_sha256':h.config['certificate_sha256']},'ticket':grant['ticket']}
    (profile/'bootstrap.json').write_text(json.dumps(value),encoding='utf-8');return profile

def protocol(binaries):
    import sqlite3
    h=Hosted();bridges=[];checks=[]
    def start(kind,profile):b=Bridge(binaries[kind],profile);bridges.append(b);return b
    try:
        enable(h);mp=configure(h,'manager','desktop');sp=configure(h,'sales','sales-desktop');sp2=configure(h,'sales','sales-desktop-2')
        sales_ticket=json.loads((sp/'bootstrap.json').read_text(encoding='utf-8'))['ticket']
        manager=start('manager',mp);m=manager.ok('bootstrap');assert m['session']['role']=='admin' and 'token' not in json.dumps(m) and 'ticket' not in json.dumps(m);checks.append('manager_native_bootstrap_without_secret_IPC')
        assert manager.call('connect',connection={},username='admin',password='123456').get('error') # DTO invalid even before dispatcher.
        # Use valid shape to prove the manual-login branch itself is disabled.
        conn={'url':f'https://127.0.0.1:{h.port}','certificate_pem':'','certificate_sha256':''}
        assert manager.call('connect',connection=conn,username='admin',password='123456')['error']['code']=='MANUAL_LOGIN_DISABLED';checks.append('formal_manual_login_direct_invoke_rejected')
        sales=start('sales',sp);sales2=start('sales',sp2);s=sales.ok('bootstrap');s2=sales2.ok('bootstrap');assert s['session']['subject']==s2['session']['subject'];assert 'cost' not in json.dumps(sales.ok('prices'));checks.append('two_devices_same_stable_sales_actor_and_filtered_prices')
        assert not (sp/'bootstrap.json').exists() and (sp/'device.bin').exists()
        if os.name=='nt':assert b'ticket' not in (sp/'device.bin').read_bytes()
        sales.close();bridges.remove(sales);sales=start('sales',sp);assert sales.ok('bootstrap')['session']['subject']==s['session']['subject'];checks.append('restart_uses_same_DPAPI_device_and_actor')
        snap={'price_version_id':'fixture-v1','lines':[{'line_kind':'normal','product_id':'单件','q':'2','h':'','w':'','name':''}]};details={'customer':'isolated','order_ref':'device-manager','wechat':''}
        manager.ok('calculate',snapshot=snap,draft_revision='1');receipt=manager.ok('submit',snapshot=snap,details=details,draft_revision='1');assert sales.call('order',order_id=receipt['order_id'])['error']['code']=='NOT_FOUND';assert sales.call('backup')['error']['code']=='ADMIN_REQUIRED';checks.append('sales_cannot_read_other_actor_or_backups')
        sales.ok('calculate',snapshot=snap,draft_revision='1');own=sales.ok('submit',snapshot=snap,details={**details,'order_ref':'device-sales'},draft_revision='1');assert sales2.ok('order',order_id=own['order_id'])['order_id']==own['order_id'];checks.append('same_actor_devices_share_own_orders_only')
        with closing(sqlite3.connect(h.host_root/'private/devices.sqlite3')) as c, c:c.execute('UPDATE device_sessions SET expires=0')
        assert sales.call('prices')['error']['status']==401;assert sales.ok('bootstrap')['session']['subject']==s['session']['subject'];checks.append('expired_session_recovers_without_password_or_identity_change')
        manager.ok('bootstrap');manager.ok('calculate',snapshot=snap,draft_revision='2');h.fault.write_text('after_commit',encoding='utf-8');assert manager.call('submit',snapshot=snap,details={**details,'order_ref':'device-unknown'},draft_revision='2')['error']['code']=='COMMIT_UNKNOWN';assert (mp/'pending.bin').is_file()
        manager.close();bridges.remove(manager);h.restart();manager=start('manager',mp);assert manager.ok('bootstrap')['session']['pending'];recovered=manager.ok('recover',retry=False);assert recovered['result']['income_cents']=='2000' and not recovered['pending'];assert manager.ok('orders',q='',state='',offset=0,view='')['total']==3;checks.append('unknown_commit_restart_queries_original_receipt_without_duplicate')
        sales.ok('calculate',snapshot=snap,draft_revision='2')
        h.fault.write_text('after_commit',encoding='utf-8')
        assert sales.call('submit',snapshot=snap,details={**details,'order_ref':'revoked-pending'},draft_revision='2')['error']['code']=='COMMIT_UNKNOWN'
        h.restart()
        assert sales.ok('bootstrap')['session']['pending']
        pending_bytes=(sp/'pending.bin').read_bytes()
        copied=h.root/'copied';copied.mkdir();(copied/'777-isolated-profile.json').write_text('{"production":false}');shutil.copyfile(sp/'device.bin',copied/'device.bin');copy=start('sales',copied);assert copy.call('bootstrap')['error']['code']=='DEVICE_PROFILE_MISMATCH';checks.append('copied_credential_rejected_in_other_profile')
        sales2.ok('bootstrap')
        admin=h.client('manager');devices=admin.request('GET','/v1/devices')['devices'];
        with closing(sqlite3.connect(h.host_root/'private/devices.sqlite3')) as c:key=c.execute('SELECT device_id FROM grants WHERE digest=?',(hashlib.sha256(sales_ticket.encode()).hexdigest(),)).fetchone()[0]
        admin.request('POST','/v1/devices/'+key,{})
        # Revoke both? Exactly one of the two devices must remain authorized.
        outcomes=[sales.call('prices'),sales2.call('prices')];assert sum('ok' in x for x in outcomes)==1;checks.append('one_device_revocation_rejects_live_session_without_affecting_peer')
        # Operator reauthorization replaces only the revoked device credential.
        target=sales if 'error' in outcomes[0] else sales2
        target_profile=sp if target is sales else sp2
        replacement=configure(h,'sales','replacement-material')
        shutil.copyfile(replacement/'bootstrap.json',target_profile/'bootstrap.json')
        assert target.ok('bootstrap')['session']['subject']==s['session']['subject']
        assert target_profile==sp and (sp/'pending.bin').read_bytes()==pending_bytes
        assert target.ok('recover',retry=False)['result']['income_cents']=='2000'
        assert manager.ok('orders',q='',state='',offset=0,view='')['total']==4
        checks.append('operator_new_grant_reauthorizes_revoked_device_without_deleting_pending')
        from native_host_fixture import restore_data_backup
        before=h.service.ledger.inventory();backup=admin.request('POST','/v1/backup',{'kind':'daily'})
        restored=h.root/'restored';restore_data_backup(h,backup,restored)
        assert not (restored/'private/devices.sqlite3').exists()
        with closing(sqlite3.connect(restored/'private/auth.sqlite3')) as c:
            assert c.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
            assert c.execute('SELECT username FROM users WHERE enabled=1').fetchall()==[('recovered-manager',)]
        assert command('inspect',root=restored)['inventory']==before;checks.append('v1_data_restore_preserves_ledger_without_old_devices_sessions_grants')
        return {'status':'passed','checks':checks,'Windows_DPAPI':os.name=='nt','production_paths_accessed':False}
    finally:
        for b in bridges:b.close()
        h.close()

def native(binary,kind,out,progress,presentation=False):
    from p07_native_window import close_window,cleanup_webview_sandbox
    out.mkdir();h=Hosted(font=str(ROOT/'desktop/public/fonts/NotoSansSC-VF.ttf') if presentation else None);process=None;result=None
    scenario=None
    try:
        enable(h);profile=configure(h,kind,'desktop');scenario=SimpleNamespace(host=h,profile=profile,close=h.close)
        if presentation:
            public=h.root/'中文 报价图片';public.mkdir()
            with h.service.auth.connection() as c:c.execute('UPDATE preferences SET export_dir=?,image_dir=?,revision=revision+1 WHERE id=1',(str(public),str(public)))
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        env=dict(os.environ)
        for key in ['WEBVIEW2_USER_DATA_FOLDER','WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']:env.pop(key,None)
        with (out/'process.log').open('wb') as log:
            process=subprocess.Popen([str(binary),'--verification-window','--profile',str(profile),'--debug-port',str(port)],stdout=log,stderr=subprocess.STDOUT,env=env)
            record=progress.run([shutil.which('node'),str(ROOT/'desktop/tests/windows-autostart.mjs'),str(port),str(out),kind,*(['presentation'] if presentation else [])],timeout=240 if presentation else 150)
            if record['exit_code']:raise RuntimeError('ACTUAL_DEVICE_WINDOW_FAILED')
            result=json.loads((out/'native-autostart.json').read_text(encoding='utf-8'))
            if presentation:
                from PIL import Image,ImageChops
                images=sorted(public.rglob('*.png'));assert len(images)==2
                records=[]
                for index,path in enumerate(images):
                    with Image.open(path) as picture:
                        picture.load();assert picture.width==1200 and picture.height==1840 and picture.info['777_format']=='777-output-v1'
                        assert ImageChops.difference(picture.crop((0,picture.height-80,picture.width,picture.height)),Image.new('RGB',(picture.width,80),'white')).getbbox()
                        records.append({'width':picture.width,'height':picture.height,'job_id':picture.info['777_job_id'],'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
                    shutil.copyfile(path,out/f'published-quote-{index+1}.png')
                assert records[0]['job_id']!=records[1]['job_id'] and h.service.ledger.inventory()['counts']['orders']==1 and h.service.ledger.inventory()['counts']['lines']==40
                result['published_images']={'files':records,'Chinese_path':True,'no_overwrite':True,'order_count_unchanged':True,'saved_lines':40,'last_line_pixels_present':True}
                result['presentation']=json.loads((out/'presentation.json').read_text(encoding='utf-8'))
                from p07_native_window import Windows,main_window
                import ctypes
                from ctypes import wintypes
                target=main_window(Windows().owned(process.pid),process.pid,'记账器')
                user=ctypes.WinDLL('user32',use_last_error=True);user.GetDpiForWindow.argtypes=[wintypes.HWND];user.GetDpiForWindow.restype=wintypes.UINT
                result['actual_OS_window_DPI']=user.GetDpiForWindow(target['hwnd']);assert result['actual_OS_window_DPI']>0
                result['physical_multi_monitor_and_other_OS_DPI']='requires_user_hardware_observation'
            result['close']=close_window(process,'记账器',out/'close.json')
        if presentation and kind=='manager':
            # Own the same loopback port after the real fixture host exits. Hold
            # TLS negotiation to prove a read-only bootstrap cannot trap close.
            h.stop();connecting=out/'connecting';connecting.mkdir()
            probe=socket.socket();probe.bind(('127.0.0.1',0));port=probe.getsockname()[1];probe.close()
            listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            connections=[];accepted=threading.Event()
            try:
                listener.bind(('127.0.0.1',h.port));listener.listen(1);listener.settimeout(20)
                def hold():
                    try:
                        connection,_=listener.accept();connections.append(connection);accepted.set()
                    except OSError:pass
                worker=threading.Thread(target=hold,daemon=True);worker.start()
                with (connecting/'process.log').open('wb') as log:
                    process=subprocess.Popen([str(binary),'--verification-window','--profile',str(profile),'--debug-port',str(port)],stdout=log,stderr=subprocess.STDOUT,env=env)
                    check=progress.run([shutil.which('node'),str(ROOT/'desktop/tests/windows-autostart.mjs'),str(port),str(connecting),kind,'connecting'],timeout=45)
                    if check['exit_code'] or not accepted.wait(1):raise RuntimeError('PENDING_NATIVE_CONNECTION_NOT_OBSERVED')
                    result['blocked_connection_close']=close_window(process,'记账器',connecting/'close.json')
                    assert result['blocked_connection_close']['elapsed_seconds']<3
            finally:
                listener.close()
                for connection in connections:connection.close()
                worker.join(timeout=1) if 'worker' in locals() else None

        return result
    finally:
        if process and process.poll() is None:stop_tree(process)
        if scenario:cleanup_webview_sandbox(scenario,out/'cleanup.json')
        else:h.close()
        if result:result['sandbox_cleaned']=True

def main(argv=None):
    p=argparse.ArgumentParser();mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--windows-smoke',action='store_true');mode.add_argument('--checks-only',action='store_true');p.add_argument('--presentation',action='store_true');p.add_argument('--jobs',type=int,choices=range(1,9),default=1);p.add_argument('--output',required=True);a=p.parse_args(argv)
    out=new_output(a.output);report={'task':'P07-03' if a.presentation else 'P07-02','status':'running','environment':{'os':platform.system(),'python':platform.python_version()},'commands':[],'production_paths_accessed':False,'protocol':None,'native':None,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'worktree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())}
    progress=Progress(out,report,a.jobs);progress.save()
    try:
        if a.windows_smoke and os.name!='nt':raise RuntimeError('ACTUAL_WINDOWS_REQUIRED')
        paths=preflight(progress,native=a.windows_smoke)
        def run(cmd):
            if progress.run(cmd)['exit_code']:raise RuntimeError('BUILD_OR_CHECK_FAILED')
        if not (ROOT/'desktop/node_modules').is_dir():run([paths['npm'],'ci','--prefix','desktop','--ignore-scripts','--no-audit','--no-fund'])
        run([paths['npm'],'--prefix','desktop','run','build'])
        run([paths['cargo'],'+1.97.1','build','--locked','--release','-j',str(a.jobs),'-p','quote-host','-p','quote-ledger'])
        binaries={}
        for kind in ['manager','sales']:
            progress.stage('构建隔离验证用 '+kind+' 桌面端')
            run([paths['cargo'],'+1.97.1','build','--locked','--release','-j',str(a.jobs),'-p','quote-desktop','--features','verification,custom-protocol,'+kind])
            binaries[kind]=out/(kind+EXT);shutil.copyfile(ROOT/'target/release'/('quote-desktop'+EXT),binaries[kind]);os.chmod(binaries[kind],0o700)
        progress.stage('真实 Rust HTTPS 设备认证、角色隔离和 v5 独立恢复')
        report['protocol']=protocol(binaries);progress.save()
        if a.windows_smoke:
            report['native']=[]
            for kind in ['manager','sales']:progress.stage('实际 WebView2 无登录进入 '+kind);report['native'].append(native(binaries[kind],kind,out/kind,progress,a.presentation));progress.save()
        if a.presentation:report['presentation_acceptance']='Actual OS DPI/physical multi-monitor and user visual acceptance pending; CDP emulation is separate.'
        report['status']='Windows_device_auth_and_native_autostart_passed_acceptance_pending' if a.windows_smoke else 'auxiliary_device_protocol_passed_actual_Windows_pending'
    except (Exception,KeyboardInterrupt) as e:
        report['status']='interrupted' if isinstance(e,KeyboardInterrupt) else 'failed';report['failure']=type(e).__name__+': '+str(e);(out/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
    finally:
        for kind in ['manager','sales']:(out/(kind+EXT)).unlink(missing_ok=True)
        files=[p for folder in ['desktop','crates','tools'] for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ['.rs','.py','.ts','.tsx','.mjs','.json','.toml','.css','.svg'] and not any(part in p.parts for part in ['node_modules','dist','gen','test-results','playwright-report','__pycache__'])]
        files += list((ROOT/'desktop/resources/licenses').glob('*.txt'))
        if a.presentation:
            assets=json.loads((ROOT/'desktop/resources/fonts.json').read_text(encoding='utf-8'))['assets']
            report['font_assets']=[{'file':x['file'],'expected_sha256':x['sha256'],'sha256':hashlib.sha256((ROOT/'desktop/public/fonts'/x['file']).read_bytes()).hexdigest() if (ROOT/'desktop/public/fonts'/x['file']).is_file() else None,'bytes':(ROOT/'desktop/public/fonts'/x['file']).stat().st_size if (ROOT/'desktop/public/fonts'/x['file']).is_file() else None,'source':x['url']} for x in assets]
        files += [ROOT/n for n in ['Cargo.toml','Cargo.lock','rust-toolchain.toml','docs/verification/P07-02-device-schema.sql','.github/workflows/p07-windows.yml']]
        report['implementation_sha256_LF']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in sorted(files)}
        progress.save()
    print(json.dumps({k:v for k,v in report.items() if k not in ['commands','implementation_sha256_LF']},ensure_ascii=False,indent=2));return 0 if 'passed' in report['status'] else 1
if __name__=='__main__':raise SystemExit(main())
