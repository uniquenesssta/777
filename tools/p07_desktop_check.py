"""P07-01 isolated desktop implementation evidence; native GUI requires actual Windows."""
import argparse,ctypes,hashlib,json,os,platform,shutil,socket,subprocess,sys,tempfile,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(ROOT/'tests')]
from p01_validation import new_output
from p06_core_check import run

def fingerprints():
    paths=[p for p in (ROOT/'desktop').rglob('*') if p.is_file() and not any(n in p.relative_to(ROOT/'desktop').parts for n in ['node_modules','dist','gen','test-results','playwright-report'])]
    paths += [ROOT/n for n in ['Cargo.toml','Cargo.lock','tools/p07_desktop_check.py','tools/p07_desktop_fixture.py','docs/design/figma-state.json','docs/design/figma-tokens.json']]
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n') if p.suffix not in ['.ico','.png'] else p.read_bytes()).hexdigest() for p in sorted(paths)}
def protocol_check():
    from p07_desktop_fixture import Scenario
    from quote_service.journal import MemoryJournal
    s=Scenario();checks=[]
    def call(action,**fields):
        v=s.call(dict(action=action,**fields))
        if 'error' in v:raise AssertionError(v['error'])
        return v['ok']
    def refused(action,code,**fields):
        v=s.call(dict(action=action,**fields));assert v.get('error',{}).get('code')==code,v
    snap={'price_version_id':'2026.10.13','lines':[{'line_kind':'normal','product_id':'安装服务','q':'2','h':'','w':'','name':''}]}
    try:
        conn=s.connection();bad={**conn,'certificate_sha256':'0'*64};refused('connect','CERTIFICATE_PIN_MISMATCH',connection=bad,username='manager',password=s.host.password);checks.append('certificate_pin_rejected_before_request')
        admin=call('connect',connection=conn,username='manager',password=s.host.password);assert admin['role']=='admin' and 'token' not in admin;checks.append('real_Rust_HTTPS_login_no_token_crosses_IPC')
        result=call('calculate',snapshot=snap,draft_revision='9007199254740993');assert result['draft_revision']=='9007199254740993' and result['result']['totals']['income_cents']=='20000'
        refused('submit','CALCULATION_STALE',snapshot=snap,details={'customer':'客户','order_ref':'00003','wechat':''},draft_revision='9007199254740994')
        receipt=call('submit',snapshot=snap,details={'customer':'客户','order_ref':'00003','wechat':''},draft_revision='9007199254740993');order=call('order',order_id=receipt['order_id']);assert order['details']['order_ref']=='00003' and order['income_cents']=='20000' and order['revision']=='1';checks.append('exact_cents_revision_and_frozen_draft_submission')
        call('note',order_id=order['order_id'],expected_revision=order['revision'],body='保留原备注');order=call('order',order_id=order['order_id']);assert order['revision']=='2'
        for state,reason in [('void','隔离验证作废'),('active','隔离验证恢复')]:
            call('set_state',order_id=order['order_id'],expected_revision=order['revision'],state=state,reason=reason);order=call('order',order_id=order['order_id']);assert order['state']==state and order['income_cents']=='20000' and order['notes'][0]['body']=='保留原备注'
        checks.append('append_only_note_void_restore_original_amount_and_revision')
        first=call('orders',q='',state='',offset=0,view='');second=call('orders',q='',state='',offset=20,view=first['view']);assert first['total']==26 and len(first['orders'])==20 and len(second['orders'])==6;checks.append('full_20_row_pagination_and_view_binding')
        before=s.host.service.ledger.inventory();job=call('create_output',order_id=order['order_id'],expected_revision=order['revision'],kind='excel_quote')
        deadline=time.monotonic()+20
        while True:
            jobs=call('outputs')['jobs'];found=next(j for j in jobs if j['job_id']==job['job_id'])
            if found['state']=='done':break
            assert found['state']!='failed' and time.monotonic()<deadline;time.sleep(.05)
        assert s.host.service.ledger.inventory()==before;checks.append('native_output_task_does_not_rebook_financial_order')
        call('disconnect');sales=call('connect',connection=conn,username='sales-one',password=s.host.password);assert sales['role']=='sales'
        projection=call('prices');assert 'cost' not in json.dumps(projection);listing=call('orders',q='',state='',offset=0,view='');assert listing['total']==23 and 'cost_cents' not in json.dumps(listing) and 'profit_cents' not in json.dumps(listing)
        refused('order','NOT_FOUND',order_id=order['order_id']);refused('set_state','ADMIN_REQUIRED',order_id=order['order_id'],expected_revision=order['revision'],state='void',reason='denied');refused('backup','ADMIN_REQUIRED');checks.append('sales_DTO_other_actor_and_management_commands_restricted')
        call('disconnect');call('connect',connection=conn,username='manager',password=s.host.password)
        call('calculate',snapshot=snap,draft_revision='2');s.host.fault.write_text('after_commit',encoding='utf-8');refused('submit','COMMIT_UNKNOWN',snapshot=snap,details={'customer':'unknown','order_ref':'original-only','wechat':''},draft_revision='2')
        assert (s.profile/'pending.bin').exists();s.host.restart();s.stop_bridge();s.start_bridge();session=call('connect',connection=conn,username='sales-one',password=s.host.password);assert session['pending'];refused('recover','PENDING_IDENTITY_MISMATCH',retry=True)
        call('disconnect');session=call('connect',connection=conn,username='manager',password=s.host.password);assert session['pending'];recovered=call('recover',retry=False);assert not recovered['pending'] and recovered['result']['income_cents']=='20000' and recovered['path']=='/v1/orders';assert not (s.profile/'pending.bin').exists()
        again=call('recover',retry=True);assert not again['pending'] and again['result'] is None;assert s.host.service.ledger.inventory()['counts']['orders']==27;checks.append('native_host_and_desktop_restart_original_receipt_identity_and_no_duplicate')
        large={**snap,'lines':[{'line_kind':'normal','product_id':'户外写真','q':'1','h':'10000000','w':'1000000','name':''}]};v=call('calculate',snapshot=large,draft_revision='3')['result'];assert v['totals']['income_cents']=='20000000000000000';checks.append('money_above_JavaScript_integer_limit_remains_exact_string')
        call('calculate',snapshot=snap,draft_revision='4');p=call('prices');updated={k:v for k,v in p.items() if k in ['price_version_id','items']};updated['price_version_id']='new-published-version';s.host.client('manager').mutate('/v1/prices',{'prices':updated,'expected_price_version_id':p['price_version_id']},MemoryJournal())
        response=s.call({'action':'submit','snapshot':snap,'details':{'customer':'','order_ref':'old-price-refused','wechat':''},'draft_revision':'4'});assert 'error' in response and response['error']['status']==409;assert s.host.service.ledger.inventory()['counts']['orders']==27;assert not (s.profile/'pending.bin').exists();checks.append('server_price_change_refuses_stale_confirmation_without_booking')
        out={'status':'passed','checks':checks,'actual_transport':'Rust desktop IPC dispatcher -> Rustls pinned HTTPS -> standalone Rust host','production_paths_accessed':False,'Windows_DPAPI':os.name=='nt','scope':'owned temporary profile, synthetic accounts/prices/orders, no installed service or real data'}
    finally:s.close()
    out['sandbox_cleaned']=True;return out

def native_window(output):
    if os.name!='nt' or platform.system()!='Windows':raise RuntimeError('ACTUAL_WINDOWS_REQUIRED')
    from p07_desktop_fixture import Scenario,CLIENT
    s=Scenario();proc=None
    try:
        s.stop_bridge();sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        fixture=output/'private-window-fixture.json';fixture.write_text(json.dumps(s.fixture(),ensure_ascii=True),encoding='utf-8')
        env=dict(os.environ,WEBVIEW2_USER_DATA_FOLDER=str(s.profile/'webview2'),WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={port} --remote-debugging-address=127.0.0.1')
        proc=subprocess.Popen([str(CLIENT),'--verification-window','--profile',str(s.profile)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            checked=run([shutil.which('node'),str(ROOT/'desktop/tests/windows-smoke.mjs'),str(fixture),str(port),str(output)],timeout=150)
        finally:fixture.unlink(missing_ok=True)
        if checked['exit_code']:raise RuntimeError('NATIVE_WEBVIEW_CHECK_FAILED:'+checked['stderr'][-1500:])
        from ctypes import wintypes
        user=ctypes.WinDLL('user32',use_last_error=True);callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)];user.GetWindowThreadProcessId.restype=wintypes.DWORD
        user.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM];user.PostMessageW.restype=wintypes.BOOL
        def close(hwnd,_):
            pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value==proc.pid:user.PostMessageW(hwnd,0x10,0,0)
            return True
        visitor=callback(close);user.EnumWindows.argtypes=[callback,wintypes.LPARAM];user.EnumWindows.restype=wintypes.BOOL;user.EnumWindows(visitor,0)
        proc.communicate(timeout=30);assert proc.returncode==0
        report=json.loads((output/'native-webview.json').read_bytes());report['native_window_close_and_process_exit']=True
        return report
    finally:
        (output/'private-window-fixture.json').unlink(missing_ok=True)
        if proc and proc.poll() is None:proc.terminate();proc.communicate(timeout=20)
        s.close()

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group(required=True);m.add_argument('--windows-smoke',action='store_true');m.add_argument('--ci-checks',action='store_true');m.add_argument('--checks-only',action='store_true');p.add_argument('--output',required=True);a=p.parse_args(argv);output=new_output(a.output)
    report={'task':'P07-01','status':'running','environment':{'os':platform.system(),'python':platform.python_version()},'commands':[],'native_window':None,'protocol':None,'production_paths_accessed':False,'acceptance':'pending_actual_Windows_visual_and_interaction'}
    font_temp=None;previous_font=os.environ.get('P06_CI_FONT_FILE')
    try:
        if (a.windows_smoke or a.ci_checks) and (os.name!='nt' or platform.system()!='Windows'):raise RuntimeError('ACTUAL_WINDOWS_REQUIRED')
        report['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,encoding='utf-8').strip();report['worktree_dirty']=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True,encoding='utf-8').strip());report['implementation_sha256_LF']=fingerprints()
        cargo=shutil.which('cargo');npm=shutil.which('npm');node=shutil.which('node')
        if not all([cargo,npm,node]):raise RuntimeError('NODE_24_NPM_AND_RUST_1_97_1_REQUIRED')
        commands=[[node,'--version'],[shutil.which('rustc'),'+1.97.1','-vV'],[npm,'ci','--prefix','desktop','--ignore-scripts','--no-audit','--no-fund'],[npm,'--prefix','desktop','run','build'],[npm,'--prefix','desktop','test'],[cargo,'+1.97.1','fmt','--all','--','--check'],[cargo,'+1.97.1','clippy','--locked','--workspace','--all-targets','--features','quote-desktop/verification','--','-D','warnings'],[cargo,'+1.97.1','test','--locked','--workspace','--features','quote-desktop/verification'],[cargo,'+1.97.1','build','--release','--locked','-j','2','-p','quote-host','-p','quote-ledger','-p','quote-desktop','--features','quote-desktop/verification']]
        for command in commands:
            record=run(command,timeout=900);report['commands'].append(record)
            if record['exit_code']:raise RuntimeError('DESKTOP_CHECK_COMMAND_FAILED')
            if command[0]==node and int(record['stdout'].lstrip('v').split('.')[0])<24:raise RuntimeError('NODE_24_REQUIRED')
            if len(command)>2 and command[2]=='-vV' and ((a.windows_smoke or a.ci_checks) and 'host: x86_64-pc-windows-msvc' not in record['stdout']):raise RuntimeError('NATIVE_MSVC_REQUIRED')
        report['protocol']=protocol_check()
        from p06_ci_fonts import prepare,SHA
        if previous_font:
            font=Path(previous_font);raw=font.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=SHA:raise RuntimeError('CI_FONT_HASH_MISMATCH')
            report['browser_font_fixture']={'sha256':SHA,'source':'explicit hash-verified fixture','scope':'test browser only; no product or system font installation'}
        else:
            font_temp=tempfile.TemporaryDirectory(prefix='777-p07-browser-font-');font_root=Path(font_temp.name)/'font';report['browser_font_fixture']=prepare(font_root);font=font_root/'NotoSansSC-VF.ttf'
        os.environ['P06_CI_FONT_FILE']=str(font)
        browser=run([npm,'--prefix','desktop','run','test:ui'],timeout=600);report['commands'].append(browser)
        ui=ROOT/'desktop/test-results/report.json'
        if ui.exists():report['browser_tests']=json.loads(ui.read_text(encoding='utf-8')).get('stats')
        if browser['exit_code']:raise RuntimeError('BROWSER_INTERACTION_FAILED')
        if a.windows_smoke:report['native_window']=native_window(output)
        report['status']='Windows_Tauri_native_window_passed_visual_acceptance_pending' if a.windows_smoke else 'Windows_CI_build_protocol_and_browser_passed_native_window_pending' if a.ci_checks else 'auxiliary_protocol_and_browser_passed_actual_Windows_pending'
    except Exception as e:report['status']='failed';report['failure']=type(e).__name__+': '+str(e);report['failure_traceback']=traceback.format_exc()
    finally:
        if previous_font is None:os.environ.pop('P06_CI_FONT_FILE',None)
        else:os.environ['P06_CI_FONT_FILE']=previous_font
        if font_temp:font_temp.cleanup()
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k not in ['commands','implementation_sha256_LF','failure_traceback']},ensure_ascii=False,indent=2));return 1 if report['status']=='failed' else 0
if __name__=='__main__':raise SystemExit(main())
