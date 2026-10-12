"""P05-02 isolated HTTPS/auth/client checks; no live E/share/deployment access."""
import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import sqlite3
import ssl
import subprocess
import sys
import time
import traceback
import unittest
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(ROOT/'tests')]
from p01_validation import new_output
from p03_format_check import case_ids
from quote_core import QuoteSnapshot,NormalLine,DraftDetails
from quote_service.journal import Journal
from quote_app.service_client import application_type

PACKAGES={'uvicorn':'0.50.0','h11':'0.16.0','click':'8.5.0','cryptography':'50.0.1'}


def dependencies():
    result=[]
    for name,version in PACKAGES.items():
        try:actual=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:actual=None
        result.append({'package':name,'expected':version,'version':actual,'status':'available' if actual==version else 'mismatch_or_missing'})
    return result


def fingerprints():
    patterns=['quote_service/*.py','quote_app/*.py','quote_core/*.py','quote_ledger/*.py','quote_files/*.py']
    paths={p for pattern in patterns for p in ROOT.glob(pattern)}
    paths.update(ROOT/p for p in ['requirements-service.txt','tools/quote_service_host.py','tools/run_quote_client.py','tools/p05_service_check.py',
        'tests/service_fixture.py','tests/test_service_boundary.py','tests/test_service_controller.py','tests/test_service_recovery.py','tests/test_p05_service_check.py',
        'docs/baseline/p01-04-golden.json'])
    manifest=json.loads((ROOT/'docs/baseline/manifest.json').read_text(encoding='utf-8'))
    paths.update(ROOT/entry['path'] for entry in manifest['files'])
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in sorted(paths)}


def run_checks():
    suite=unittest.defaultTestLoader.loadTestsFromNames(['test_service_boundary','test_service_controller','test_service_recovery','test_p05_service_check'])
    ids=list(case_ids(suite));log=io.StringIO();start=time.monotonic()
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    return {'status':'passed' if result.wasSuccessful() else 'failed','tests_run':result.testsRun,'failures':len(result.failures),
            'errors':len(result.errors),'skipped':result.skipped,'elapsed_seconds':time.monotonic()-start,'test_ids':ids,'log':log.getvalue(),
            'failure_details':[{'test_id':case.id(),'error':trace.strip().splitlines()[-1]} for case,trace in [*result.errors,*result.failures]]}


def windows_smoke():
    if platform.system()!='Windows':raise RuntimeError('Actual Windows required')
    from service_fixture import Hosted
    import tkinter as tk
    host=Hosted();errors=[];applications=[]
    try:
        # Actual DPAPI journal round-trip and original receipt recovery.
        client=host.client();journal=Journal(host.root/'native-pending.bin');original=client.request
        def lose_reply(method,path,data=None):
            result=original(method,path,data)
            if path=='/v1/orders':raise OSError('isolated reply loss')
            return result
        from quote_service.client import CommitUnknown
        with patch.object(client,'request',side_effect=lose_reply):
            try:client.submit(QuoteSnapshot('fixture-v1',(NormalLine('单件','4'),)),DraftDetails('隔离客户','隔离订单','隔离微信'),journal)
            except CommitUnknown:pass
            else:raise AssertionError('Expected reply-loss outcome')
        encrypted=journal.path.read_bytes()
        assert b'777-pending-v1' not in encrypted and '隔离客户'.encode() not in encrypted
        saved=journal.read();assert saved['body']['details']['customer']=='隔离客户'
        before=host.service.ledger.inventory();receipt=client.check_pending(journal)
        assert receipt['result'] is not None and journal.read() is None and host.service.ledger.inventory()==before
        for role,user in [('manager','manager'),('sales','sales-one')]:
            settings=host.client(user).settings;profile=host.root/(role+'-gui.json')
            profile.write_text(json.dumps(settings),encoding='utf-8')
            root=tk.Tk();root.report_callback_exception=lambda kind,value,tb:errors.append(kind.__name__+': '+str(value))
            app=None
            try:
                # These methods must never be reached by the opt-in client.
                with (patch('quote_app.connections.ConnectionMixin._restore_connection',side_effect=AssertionError('legacy source access')),
                     patch('quote_app.integration.QuoteApplicationMixin._read_price_candidate',side_effect=AssertionError('legacy price access')),
                     patch('quote_app.integration.QuoteApplicationMixin._write_quote_excel',side_effect=AssertionError('legacy workbook write'))):
                    app=application_type(role,profile)(root)
                    def wait(predicate):
                        deadline=time.monotonic()+20
                        while not predicate() and time.monotonic()<deadline:
                            root.update();time.sleep(.005)
                        assert predicate(), 'GUI operation not completed: '+str(app.feedback_var.get())
                    app.service_password.set(host.password);app.login_service()
                    wait(lambda:app._svc_prices is not None and not app._svc_jobs.tasks)
                    assert app.service_password.get()==''
                    app.add_calc_row('服务单件','单件',True);app.calc_rows[-1]['q'].set('4')
                    app.add_discount_calc_row('折扣');app.calc_rows[-1]['discount_choice'].set('90%')
                    app.calculate(notify=False);wait(lambda:app._svc_result is not None and not app._svc_jobs.tasks)
                    assert app.total_val.get()=='总计：36.00 元'
                    assert str(app.calc_export_button.cget('text'))=='提交订单'
                    app.notebook.select(app.calc_page);root.update()
                    app.calc_export_button.invoke();wait(lambda:not app._svc_jobs.tasks)
                    app.refresh_excel_files();wait(lambda:bool(app._svc_orders) and not app._svc_jobs.tasks)
                    identifier=next(iter(app._svc_orders));app.service_order_tree.selection_set(identifier)
                    app.load_current_excel_sheet();wait(lambda:not app._svc_jobs.tasks)
                    assert '金额' in app.service_detail_text.get('1.0','end')
                    if role=='sales':
                        assert '成本' not in app.service_detail_text.get('1.0','end') and '利润' not in app.service_detail_text.get('1.0','end')
                        assert all('cost' not in item for item in app._svc_prices['items'])
                        assert all(str(entry.cget('state'))=='readonly' for entry in app.service_directory_entries.values())
                        assert app.delete_current_excel_row() is False
                    applications.append({'role':role,'startup':'ok','HTTPS_login':True,'password_widget_cleared':True,
                        'remote_calculation_income_cents':'3600','submit_button_books_order':True,'remote_listing_and_detail':True,
                        'sales_fields_and_directories_restricted':True if role=='sales' else None,'legacy_source_and_workbook_callbacks_not_reached':True,'close':'pending'})
            finally:
                if app:
                    app.on_close()
                    deadline=time.monotonic()+20
                    while app._svc_jobs.writing and time.monotonic()<deadline:root.update();time.sleep(.01)
                    if app._svc_jobs.writing:raise RuntimeError('GUI write still pending; sandbox retained')
                    # If a write was pending, the poller owns final destruction.
                    try:root.update()
                    except tk.TclError:pass
                    if not app._svc_jobs.closed:raise RuntimeError('GUI job queue did not close')
                    if not app._svc_jobs.wait_closed(15):raise RuntimeError('GUI network worker not closed')
                    if applications and applications[-1]['role']==role:applications[-1]['close']='ok'
                else:root.destroy()
        assert not errors,errors
        inventory=host.service.ledger.inventory()
        backup=host.service.backup(kind='maintenance')
        from quote_ledger.backup import restore_backup
        restored=restore_backup(host.service.backups.root/backup['backup_id'],host.root/'independent.sqlite3')
        assert restored.inventory()==inventory
        from quote_service.recovery import restore as restore_service
        restored_ledger,restored_auth=restore_service(backup['service_bundle'],host.root/'restored-host','manager','isolated-new-password')
        assert restored_ledger.inventory()==inventory
        with restored_auth.connection() as c:assert c.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
        result={'status':'passed','transport':'actual loopback TCP HTTPS with pinned self-signed certificate',
                'negotiated_TLS_version':client.last_tls_version,
                'DPAPI_pending_encrypted_round_trip_and_receipt_recovery':True,'applications':applications,
                'callback_errors':errors,'inventory':inventory,'backup_independent_restore_equal':True,
                'complete_host_bundle_restore_accounts_TLS_and_maintenance':True,'old_sessions_removed_on_restore':True,
                'host_private_directory_native_security':host.config['private_security'],
                'scope':'Windows temp host, two sequential live Tk clients and real HTTPS sessions; no installed service, real E/share paths or physical two-computer deployment.',
                'sandbox_cleaned':False}
    finally:host.close()
    result['sandbox_cleaned']=True;return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--windows-smoke',action='store_true');mode.add_argument('--checks-only',action='store_true');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv);output=new_output(args.output)
    report={'task':'P05-02','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'environment':{'os':platform.system(),'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'openssl':ssl.OPENSSL_VERSION},
            'implementation_sha256_LF':fingerprints(),'dependencies':dependencies(),'status':'running','checks':None,'native_smoke':None,
            'production_paths_accessed':False,'production_files_read_or_modified':False,'real_service_installed_or_clients_switched':False,
            'P04_shared_acceptance':'deferred_by_user_due_to_power_outage','P05_02_acceptance':'pending'}
    if args.windows_smoke and platform.system()!='Windows':report.update(status='blocked',reason='Actual Windows required before any native host/GUI/DPAPI access')
    elif any(d['status']!='available' for d in report['dependencies']):report.update(status='blocked',reason='Install exact requirements-service.txt versions before checks')
    else:
        report['checks']=run_checks()
        if report['checks']['status']!='passed':report['status']='failed'
        elif args.windows_smoke:
            try:report['native_smoke']=windows_smoke();report['status']='Windows_isolated_service_passed_acceptance_pending'
            except Exception as exc:report.update(status='failed',error=f'{type(exc).__name__}: {exc}',native_error_traceback=traceback.format_exc())
        else:report['status']='auxiliary_service_checks_passed_Windows_pending'
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary={k:report[k] for k in ('task','status','environment','native_smoke')}
    if report['checks']:summary['checks']={k:report['checks'][k] for k in ('status','tests_run','failures','errors','failure_details')}
    if 'error' in report:summary['error']=report['error']
    if 'reason' in report:summary['reason']=report['reason']
    summary['report_path']=str(output/'report.json');print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0 if report['status'] in {'Windows_isolated_service_passed_acceptance_pending','auxiliary_service_checks_passed_Windows_pending'} else 2


if __name__=='__main__':raise SystemExit(main())
