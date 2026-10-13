"""P05-04: isolated Windows output/Excel-lock/Tk/protocol/complete restore check."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import time
import traceback
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(ROOT/'tests')]
from p01_validation import new_output
from p03_format_check import case_ids


def fingerprints():
    paths={*ROOT.glob('quote_service/*.py'),*ROOT.glob('quote_core/*.py'),*ROOT.glob('quote_ledger/*.py'),
           ROOT/'quote_app/service_client.py',ROOT/'tools/quote_service_host.py',Path(__file__),
           ROOT/'requirements-service.txt',ROOT/'docs/verification/P05-04-protocol.json',
           ROOT/'tests/service_fixture.py',ROOT/'tests/test_service_controller.py'}
    paths.update(ROOT/'tests'/name for name in ['test_service_outputs.py','test_service_query.py','test_output_protocol.py','test_output_controller.py','test_p05_output_check.py'])
    manifest=json.loads((ROOT/'docs/baseline/manifest.json').read_text(encoding='utf-8'))
    paths.update(ROOT/entry['path'] for entry in manifest['files'])
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in sorted(paths)}


def run_checks():
    suite=unittest.defaultTestLoader.loadTestsFromNames(['test_service_outputs','test_service_query','test_output_protocol','test_output_controller','test_p05_output_check'])
    ids=list(case_ids(suite));log=io.StringIO();start=time.monotonic()
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    return {'status':'passed' if result.wasSuccessful() else 'failed','tests_run':result.testsRun,
            'failures':len(result.failures),'errors':len(result.errors),'skipped':result.skipped,
            'elapsed_seconds':time.monotonic()-start,'test_ids':ids,'log':log.getvalue(),
            'failure_details':[{'test_id':case.id(),'error':trace.strip().splitlines()[-1]} for case,trace in [*result.errors,*result.failures]]}


def windows_smoke():
    if platform.system()!='Windows':raise RuntimeError('Actual Windows required before native output access')
    import ctypes
    from ctypes import wintypes
    import tkinter as tk
    from quote_app.service_client import application_type
    from quote_service.journal import Journal
    from quote_service.client import CommitUnknown
    from quote_core import QuoteSnapshot,NormalLine,DraftDetails
    from quote_service.hosting import load
    from quote_service.recovery import restore,manifest
    from service_fixture import Hosted
    host=Hosted();errors=[];apps=[]
    def wait(predicate,root=None):
        deadline=time.monotonic()+25
        while not predicate() and time.monotonic()<deadline:
            if root:root.update()
            time.sleep(.01)
        assert predicate(),'isolated output operation did not complete'
    try:
        client=host.client();admin=host.client('manager')
        order=client.submit(QuoteSnapshot('fixture-v1',(NormalLine('单件','2'),)),DraftDetails('隔离客户','锁定订单','隔离微信'),Journal(host.root/'order.pending'))
        original_inventory=host.service.ledger.inventory()
        task=client.mutate('/v1/outputs',{'order_id':order['order_id'],'expected_revision':1,'kind':'excel_quote','format':'777-output-v1'},Journal(host.root/'output.pending'))
        wait(lambda:client.request('GET','/v1/outputs/'+task['job_id'])['state']=='failed')
        (host.root/'reports').mkdir();(host.root/'images').mkdir()
        with host.service.auth._lock,host.service.auth.connection() as c:
            c.execute('UPDATE preferences SET export_dir=?,image_dir=?,revision=revision+1 WHERE id=1',(str(host.root/'reports'),str(host.root/'images')))
        # Synthetic fixture alone injects local paths. Production publication remains manager-only UNC.
        content=client.request('GET','/v1/outputs/'+task['job_id']+'/content')
        filename='777-'+order['order_id']+'-'+task['job_id']+'.xlsx'
        target=host.root/'reports'/filename;target.write_bytes(base64.b64decode(content['data_base64']))
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        create=kernel.CreateFileW;create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE];create.restype=wintypes.HANDLE
        close=kernel.CloseHandle;close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
        handle=create(str(target),0x80000000,0,None,3,0x80,None)
        if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
        try:
            client.mutate('/v1/outputs/'+task['job_id']+'/retry',{},Journal(host.root/'retry.pending'))
            wait(lambda:client.request('GET','/v1/outputs/'+task['job_id'])['state']=='failed')
            assert 'PermissionError' in client.request('GET','/v1/outputs/'+task['job_id'])['error']
            assert host.service.ledger.inventory()==original_inventory
        finally:
            if not close(handle):raise ctypes.WinError(ctypes.get_last_error())
        client.mutate('/v1/outputs/'+task['job_id']+'/retry',{},Journal(host.root/'retry2.pending'))
        wait(lambda:client.request('GET','/v1/outputs/'+task['job_id'])['state']=='done')
        assert hashlib.sha256(target.read_bytes()).hexdigest()==content['sha256']
        assert host.service.ledger.inventory()==original_inventory
        # Output reply loss uses the same encrypted request journal and original receipt.
        journal=Journal(host.root/'reply.pending');request=client.request
        def lost(method,path,data=None):
            result=request(method,path,data)
            if method=='POST' and path=='/v1/outputs':raise OSError('isolated output reply loss')
            return result
        with patch.object(client,'request',side_effect=lost):
            try:client.mutate('/v1/outputs',{'order_id':order['order_id'],'expected_revision':1,'kind':'quote_png','format':'777-output-v1'},journal)
            except CommitUnknown:pass
            else:raise AssertionError('Expected original pending output request')
        encrypted=journal.path.read_bytes();assert b'777-pending-v1' not in encrypted and b'quote_png' not in encrypted
        key=journal.read()['body']['request_id'];assert client.check_pending(journal)['result']['job_id']==key and journal.read() is None
        wait(lambda:client.request('GET','/v1/outputs/'+key)['state']=='done')
        assert host.service.ledger.inventory()==original_inventory
        for role,user in [('manager','manager'),('sales','sales-one')]:
            profile=host.root/(role+'-ui.json');profile.write_text(json.dumps(host.client(user).settings),encoding='utf-8')
            root=tk.Tk();root.report_callback_exception=lambda kind,value,tb:errors.append(kind.__name__+': '+str(value));app=None
            try:
                with patch('quote_app.integration.QuoteApplicationMixin._write_quote_excel',side_effect=AssertionError('legacy workbook write')):
                    app=application_type(role,profile)(root);app.service_password.set(host.password);app.login_service()
                    wait(lambda:app._svc_prices is not None and not app._svc_jobs.tasks,root)
                    app.add_calc_row('隔离单件','单件',True);app.calc_rows[-1]['q'].set('4')
                    app.add_discount_calc_row('折扣');app.calc_rows[-1]['discount_choice'].set('90%');app.calculate(notify=False)
                    wait(lambda:app._svc_result is not None and not app._svc_jobs.tasks,root)
                    app.calc_export_button.invoke();wait(lambda:app._svc_submitted is not None and not app._svc_jobs.tasks,root)
                    identity=app._svc_submitted['order_id'];before=host.service.ledger.inventory()
                    app.service_order_tree.selection_set(identity)
                    def buttons(widget):
                        found=[]
                        for child in widget.winfo_children():
                            try:
                                if child.winfo_class()=='TButton':found.append(child)
                            except tk.TclError:pass
                            found+=buttons(child)
                        return found
                    def click(label):
                        values=[button for button in buttons(root) if str(button.cget('text'))==label]
                        assert len(values)==1;values[0].invoke();wait(lambda:not app._svc_jobs.tasks,root)
                    click('导出Excel');click('生成报价图片')
                    if role=='manager':click('内部明细（私有）')
                    else:
                        assert not any(str(button.cget('text'))=='内部明细（私有）' for button in buttons(root))
                        assert all(str(entry.cget('state'))=='readonly' for entry in app.service_directory_entries.values())
                    api=host.client(user)
                    def finished():
                        jobs=[job for job in api.request('GET','/v1/outputs')['jobs'] if job['order_id']==identity]
                        return len(jobs)==(3 if role=='manager' else 2) and all(job['state']=='done' for job in jobs)
                    wait(finished,root);assert host.service.ledger.inventory()==before
                    app._svc_search.set(identity);click('搜索客户/订单号');assert set(app._svc_orders)=={identity}
                    assert app._svc_client.request('GET','/v1/orders?q='+identity)['totals']['income_cents']=='3600'
                    apps.append({'role':role,'startup':'ok','submit_button_books_once':True,'native_Excel_and_PNG_buttons':True,
                                 'internal_report_private_or_sales_button_absent':True,'inherited_directories_readonly':True if role=='sales' else None,
                                 'search_and_scoped_totals':True,'outputs_do_not_change_order_inventory':True,'close':'pending'})
            finally:
                if app:
                    app.on_close();wait(lambda:not app._svc_jobs.writing,root)
                    try:root.update()
                    except tk.TclError:pass
                    assert app._svc_jobs.closed and app._svc_jobs.wait_closed(15)
                    if apps and apps[-1]['role']==role:apps[-1]['close']='ok'
                else:root.destroy()
        assert not errors,errors
        inventory=host.service.ledger.inventory()
        assert inventory['counts']['orders']==3 and inventory['counts']['lines']==5 and inventory['revision']==4
        assert [inventory[k] for k in ('active_income_cents','active_cost_cents','active_profit_cents')]==['9200','4000','5200']
        entry=host.service.backup(kind='maintenance');assert manifest(entry['service_bundle'])['format']=='777-service-bundle-v2'
        restored,_=restore(entry['service_bundle'],host.root/'restored','manager','isolated-new-password')
        _,config,reopened=load(host.root/'restored',allow_maintenance=True);assert config['maintenance'] and restored.inventory()==inventory
        assert reopened.outputs.content(host.admin,task['job_id'])['sha256']==content['sha256']
        with reopened.auth.connection() as c:assert c.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
        result={'status':'passed','actual_Windows_exclusive_file_lock':True,'blocked_output_retains_committed_order':True,
                'unlock_and_original_job_retry_same_bytes_no_duplicate_order':True,'actual_HTTPS_DPAPI_output_receipt_recovery':True,
                'applications':apps,'callback_errors':errors,'inventory':inventory,'complete_v2_restore_tasks_bytes_accounts_and_maintenance':True,
                'host_private_security':host.config['private_security'],'scope':'Windows temp host/local synthetic output directories and two sequential real Tk/HTTPS clients; no real UNC/E/production migration or installed service.',
                'sandbox_cleaned':False}
    finally:host.close()
    result['sandbox_cleaned']=True;return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--windows-smoke',action='store_true');mode.add_argument('--checks-only',action='store_true');p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(argv);output=new_output(args.output)
    report={'task':'P05-04','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'environment':{'os':platform.system(),'python':platform.python_version(),'sqlite':sqlite3.sqlite_version},
            'implementation_sha256_LF':fingerprints(),'status':'running','checks':None,'native_smoke':None,
            'production_paths_accessed':False,'production_files_read_or_modified':False,'Windows_acceptance':'pending'}
    if args.windows_smoke and platform.system()!='Windows':report['status']='blocked_actual_Windows_required'
    else:
        report['checks']=run_checks()
        if report['checks']['status']!='passed':report['status']='failed_checks'
        elif args.checks_only:report['status']='auxiliary_checks_passed_Windows_pending'
        else:
            try:report['native_smoke']=windows_smoke();report['status']='Windows_isolated_outputs_passed_acceptance_pending'
            except Exception as exc:
                report['status']='failed_native';report['native_error']={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('implementation_sha256_LF','checks')},ensure_ascii=False,indent=2))
    if report['checks']:print(json.dumps({k:v for k,v in report['checks'].items() if k not in ('test_ids','log')},ensure_ascii=False))
    return 0 if report['status'] in {'auxiliary_checks_passed_Windows_pending','Windows_isolated_outputs_passed_acceptance_pending'} else 1


if __name__=='__main__':raise SystemExit(main())
