"""P05-01 isolated local SQLite/Windows backup checks; never the live ledger."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(ROOT/'tests')]
from p01_validation import new_output
from p03_format_check import case_ids
from quote_core import PriceItem,PriceSnapshot,QuoteSnapshot,NormalLine,DiscountLine
from quote_ledger import Ledger,Principal
from quote_ledger.backup import Backups,restore_backup
from quote_ledger import schema
from quote_ledger.security import protect_directory,_replace_dacl


def run_checks():
    suite=unittest.defaultTestLoader.loadTestsFromNames(['test_structured_ledger','test_ledger_security','test_p05_ledger_check'])
    ids=list(case_ids(suite));log=io.StringIO();started=time.monotonic()
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    return {'status':'passed' if result.wasSuccessful() else 'failed','tests_run':result.testsRun,
            'failures':len(result.failures),'errors':len(result.errors),'skipped':result.skipped,
            'elapsed_seconds':time.monotonic()-started,'test_ids':ids,'log':log.getvalue(),
            'failure_details':[{'test_id':test.id(),'error':trace.strip().splitlines()[-1]}
                for test,trace in [*result.failures,*result.errors]]}


def windows_smoke():
    if platform.system()!='Windows':raise RuntimeError('Actual Windows required before any smoke directory access')
    with tempfile.TemporaryDirectory(prefix='777-p05-native-') as temp:
        root=Path(temp);ledger=Ledger.create(root/'本地账本.sqlite3')
        admin,sales=Principal('fixture-admin','admin'),Principal('fixture-sales','sales')
        ledger.publish_prices(str(uuid.uuid4()),admin,PriceSnapshot('published-1',(PriceItem('单件','10','4','1',True),)))
        request=str(uuid.uuid4());snapshot=QuoteSnapshot('published-1',(NormalLine('单件','4'),DiscountLine('90%')))
        order=ledger.submit_order(request,sales,snapshot)
        assert ledger.submit_order(request,sales,snapshot)==order
        ledger.append_note(str(uuid.uuid4()),sales,order['order_id'],'隔离附加备注',expected_revision=1)
        ledger.set_state(str(uuid.uuid4()),admin,order['order_id'],'void','隔离作废',expected_revision=2)
        assert ledger.inventory()['active_income_cents']=='0'
        ledger.set_state(str(uuid.uuid4()),admin,order['order_id'],'active','隔离恢复',expected_revision=3)
        assert ledger.inventory()['active_income_cents']=='3600'
        manager=Backups.create(root/'隐藏备份')
        entry=manager.create_backup(ledger,kind='maintenance')
        restored=restore_backup(manager.root/entry['backup_id'],root/'独立恢复.sqlite3')
        assert restored.inventory()==ledger.inventory()
        before=restored.inventory();assert restored.submit_order(request,sales,snapshot)==order
        assert restored.inventory()==before
        security=manager.status()['security']
        assert security['hidden'] and security['system'] and security['protected_dacl']
        # Native regression: a new owned fixture must lose an extra explicit
        # Everyone grant; ordinary grants must not merely be merged into it.
        import ctypes
        fixture=root/'权限回归';fixture.mkdir()
        advapi=ctypes.WinDLL('advapi32',use_last_error=True)
        free=ctypes.WinDLL('kernel32',use_last_error=True).LocalFree
        free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p
        _replace_dacl(fixture,set(security['allowed_sids'])|{'S-1-1-0'},advapi,free)
        checked=protect_directory(fixture)
        assert checked['allowed_sids']==security['allowed_sids']
        value={'status':'passed','inventory':before,'idempotent_original_and_restored_receipts':True,
            'all_exact_amounts_and_void_restore_passed':True,
            'backup_security':{'hidden':True,'system':True,'protected_dacl':True,'allowed_principal_count':len(security['allowed_sids']),
                'extra_explicit_everyone_grant_removed_in_owned_fixture':True},
            'native_lock_and_SQLite_backup':True,'source_target_independent':True,
            'scope':'Actual Windows temp local SQLite, current Windows identity ACL/Hidden+System and independently restored backup; no E/share/live database or service installation',
            'sandbox_cleaned':False}
    value['sandbox_cleaned']=True
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--windows-smoke',action='store_true');mode.add_argument('--checks-only',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv);output=new_output(args.output)
    fingerprints={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        for p in sorted([*ROOT.glob('quote_ledger/*.py'),*ROOT.glob('quote_core/*.py'),ROOT/'quote_files/transactions.py',
            ROOT/'tests/test_structured_ledger.py',ROOT/'tests/test_ledger_security.py',ROOT/'tests/test_p05_ledger_check.py',ROOT/'tests/test_quote_core.py',
            ROOT/'tools/p05_ledger_check.py',ROOT/'docs/baseline/p01-04-golden.json'])}
    report={'task':'P05-01','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'environment':{'os':platform.system(),'python':platform.python_version(),'sqlite':sqlite3.sqlite_version},
        'implementation_sha256_LF':fingerprints,'production_paths_accessed':False,'production_files_read_or_modified':False,
        'existing_E_or_shared_directories_modified':False,'P04_shared_acceptance':'deferred_by_user_due_to_power_outage',
        'service_or_client_switch_deployed':False,'schema_version':schema.VERSION,'schema_hash':schema.expected_hash(),
        'status':'running','checks':None,'native_smoke':None,'P05_01_acceptance':'pending'}
    if args.windows_smoke and platform.system()!='Windows':
        report.update(status='blocked',reason='Actual Windows required; no native temp database, attributes or ACL operations attempted')
    else:
        report['checks']=run_checks()
        if report['checks']['status']!='passed':report['status']='failed'
        elif args.windows_smoke:
            try:
                report['native_smoke']=windows_smoke();report['status']='Windows_isolated_ledger_passed_acceptance_pending'
            except Exception as exc:report.update(status='failed',error=f'{type(exc).__name__}: {exc}',native_error_traceback=traceback.format_exc())
        else:report['status']='auxiliary_checks_passed_Windows_pending'
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary={k:report[k] for k in ('task','status','environment','P04_shared_acceptance','native_smoke')}
    if report['checks'] is not None:
        summary['checks']={k:report['checks'][k] for k in ('status','tests_run','failures','errors','failure_details') if k in report['checks']}
    if 'error' in report:summary['error']=report['error']
    summary['report_path']=str(output/'report.json')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0 if report['status'] in {'Windows_isolated_ledger_passed_acceptance_pending','auxiliary_checks_passed_Windows_pending'} else 2


if __name__=='__main__':raise SystemExit(main())
