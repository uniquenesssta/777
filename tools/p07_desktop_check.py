"""P07-01 isolated desktop implementation evidence; native GUI requires actual Windows."""
import argparse,ctypes,hashlib,json,os,platform,shutil,socket,subprocess,sys,tempfile,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(ROOT/'tests')]
from p01_validation import new_output
from p07_check_runner import Progress,preflight,build_plan,stop_tree

def fingerprints():
    paths=[p for p in (ROOT/'desktop').rglob('*') if p.is_file() and not any(n in p.relative_to(ROOT/'desktop').parts for n in ['node_modules','dist','gen','test-results','playwright-report'])]
    paths += [ROOT/n for n in ['Cargo.toml','Cargo.lock','tools/p07_desktop_check.py','tools/p07_desktop_fixture.py','tools/p07_check_runner.py','tests/test_p07_check_runner.py','docs/design/figma-state.json','docs/design/figma-tokens.json']]
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

def native_window(output,run):
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
        if proc and proc.poll() is None:stop_tree(proc);proc.communicate(timeout=20)
        s.close()

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    modes=p.add_mutually_exclusive_group(required=True)
    modes.add_argument('--windows-smoke',action='store_true',help='Preflight, minimal release build, real HTTPS and actual isolated WebView2 window')
    modes.add_argument('--ci-checks',action='store_true',help='Full Windows build, lint, unit, protocol and browser checks')
    modes.add_argument('--checks-only',action='store_true',help='Auxiliary full checks, never Windows native acceptance')
    modes.add_argument('--preflight',action='store_true',help='Check installed environment only; no dependency installation or compilation')
    p.add_argument('--jobs',type=int,choices=range(1,9),default=1,help='Cargo build/test concurrency (default 1)')
    p.add_argument('--output',required=True)
    a=p.parse_args(argv)
    output=new_output(a.output)
    full=a.ci_checks or a.checks_only
    report={'task':'P07-01','status':'running','environment':{'os':platform.system(),'python':platform.python_version()},
            'mode':'preflight' if a.preflight else 'native_window' if a.windows_smoke else 'full_CI' if a.ci_checks else 'auxiliary',
            'cargo_jobs':a.jobs,'commands':[],'native_window':None,'protocol':None,'production_paths_accessed':False,
            'acceptance':'pending_actual_Windows_visual_and_interaction'}
    progress=Progress(output,report,jobs=a.jobs)
    progress.save()
    font_temp=None
    previous_font=os.environ.get('P06_CI_FONT_FILE')
    exit_code=0
    try:
        if (a.windows_smoke or a.ci_checks) and (os.name!='nt' or platform.system()!='Windows'):
            raise RuntimeError('ACTUAL_WINDOWS_REQUIRED')
        report['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,encoding='utf-8').strip()
        report['worktree_dirty']=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True,encoding='utf-8').strip())
        report['implementation_sha256_LF']=fingerprints()
        paths=preflight(progress,native=a.windows_smoke or (a.preflight and os.name=='nt'),full=full)
        if a.preflight:
            report['status']='preflight_passed_build_not_started'
        else:
            progress.emit('\nCargo.toml / Cargo.lock 已列出 Rust 依赖，首次由 Cargo 下载。\n')
            progress.emit(f'本轮编译并发 {a.jobs}；Windows 子进程使用低于正常优先级。\n')
            report['reused_CI_scope']='Native-window mode builds required release executables; full lint/unit/browser checks remain in --ci-checks.' if a.windows_smoke else None
            for label,command in build_plan(paths,full,a.jobs):
                record=progress.run(command,label=label)
                if record['exit_code']:
                    raise RuntimeError('DESKTOP_CHECK_COMMAND_FAILED: '+label+'; '+record['log'])
            progress.stage('真实 Rust HTTPS 隔离协议验证')
            report['protocol']=protocol_check()
            progress.save()
            if full:
                progress.stage('准备仅供浏览器测试使用的字体')
                from p06_ci_fonts import prepare,SHA
                if previous_font:
                    font=Path(previous_font)
                    if hashlib.sha256(font.read_bytes()).hexdigest()!=SHA:
                        raise RuntimeError('CI_FONT_HASH_MISMATCH')
                    report['browser_font_fixture']={'sha256':SHA,'source':'explicit hash-verified fixture','scope':'test browser only; no product or system font installation'}
                else:
                    font_temp=tempfile.TemporaryDirectory(prefix='777-p07-browser-font-')
                    font_root=Path(font_temp.name)/'font'
                    report['browser_font_fixture']=prepare(font_root)
                    font=font_root/'NotoSansSC-VF.ttf'
                os.environ['P06_CI_FONT_FILE']=str(font)
                browser=progress.run([paths['npm'],'--prefix','desktop','run','test:ui'],timeout=600,label='完整浏览器交互验证')
                ui=ROOT/'desktop/test-results/report.json'
                if ui.exists():report['browser_tests']=json.loads(ui.read_text(encoding='utf-8')).get('stats')
                if browser['exit_code']:raise RuntimeError('BROWSER_INTERACTION_FAILED')
            if a.windows_smoke:
                progress.stage('启动实际 Tauri / WebView2 临时窗口并验证')
                report['native_window']=native_window(output,progress.run)
            report['status']='Windows_Tauri_native_window_passed_visual_acceptance_pending' if a.windows_smoke else 'Windows_CI_build_protocol_and_browser_passed_native_window_pending' if a.ci_checks else 'auxiliary_protocol_and_browser_passed_actual_Windows_pending'
    except KeyboardInterrupt:
        report['status']='interrupted'
        report['failure']='USER_INTERRUPTED; current command and partial log retained'
        exit_code=130
    except Exception as error:
        report['status']='failed'
        report['failure']=type(error).__name__+': '+str(error)
        report['failure_traceback']=traceback.format_exc()
        exit_code=1
    finally:
        if previous_font is None:os.environ.pop('P06_CI_FONT_FILE',None)
        else:os.environ['P06_CI_FONT_FILE']=previous_font
        if font_temp:font_temp.cleanup()
        progress.save()
    progress.emit('\n报告：'+str(output/'report.json')+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['commands','implementation_sha256_LF','failure_traceback']},ensure_ascii=False,indent=2))
    return exit_code

if __name__=='__main__':
    raise SystemExit(main())
