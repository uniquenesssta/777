"""P06-02 native ledger/protocol/backup validation. Uses only temporary hosts."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import traceback
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(ROOT/'tests')]
from p01_validation import new_output
from p03_format_check import case_ids
from p06_core_check import run,compare


def fingerprints():
    paths={ROOT/'Cargo.toml',ROOT/'Cargo.lock',ROOT/'rust-toolchain.toml',ROOT/'THIRD_PARTY_NOTICES.md',Path(__file__)}
    for pattern in ['quote_core/*.py','quote_ledger/*.py','quote_service/*.py','quote_import/*.py','quote_files/*.py']:
        paths.update(ROOT.glob(pattern))
    paths.update((ROOT/'crates').rglob('*.rs'));paths.update((ROOT/'crates').rglob('Cargo.toml'))
    paths.update(ROOT/p for p in ['tools/quote_service_host.py','tools/p06_core_check.py','tools/p06_cases.py','tools/p01_oracle.py','tests/test_rust_ledger.py','tests/test_rust_service.py','tests/rust_service_fixture.py','tests/test_p06_ledger_check.py','tests/service_fixture.py','tests/import_fixture.py','tests/test_service_boundary.py','tests/test_service_query.py','tests/test_service_outputs.py','docs/verification/P05-01-schema.sql','docs/verification/P06-02-dependencies.json','docs/verification/P06-02-protocol.json','docs/baseline/p01-04-golden.json','requirements-service.txt'])
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in sorted(paths)}


def run_checks():
    suite=unittest.defaultTestLoader.loadTestsFromNames(['test_rust_ledger','test_rust_service','test_p06_ledger_check'])
    ids=list(case_ids(suite));log=io.StringIO();result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    return dict(status='passed' if result.wasSuccessful() else 'failed',tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=result.skipped,test_ids=ids,log=log.getvalue(),failure_details=[dict(test_id=case.id(),error=trace.strip().splitlines()[-1]) for case,trace in result.failures+result.errors])


def windows_smoke():
    if os.name!='nt' or platform.system()!='Windows':raise RuntimeError('ACTUAL_WINDOWS_REQUIRED')
    from rust_service_fixture import Hosted
    from quote_service.journal import Journal
    from quote_service.client import CommitUnknown
    from quote_core import QuoteSnapshot,NormalLine,DraftDetails
    from quote_service.recovery import restore
    from quote_service.protocol import APIError
    host=Hosted()
    try:
        sales=host.client();q=QuoteSnapshot('fixture-v1',(NormalLine('单件','4'),));journal=Journal(host.root/'client-private/pending.dat')
        host.service.ledger.test_fault='after_commit'
        try:
            try:sales.submit(q,DraftDetails('000012','00003','微信'),journal)
            except CommitUnknown:pass
            else:raise AssertionError('expected native commit-unknown')
        finally:host.service.ledger.test_fault=None
        pending=journal.read();assert pending is not None
        assert b'000012' not in journal.path.read_bytes()
        recovered=sales.check_pending(journal)['result'];assert recovered['income_cents']=='4000' and journal.read() is None
        row=sales.request('GET','/v1/orders/'+recovered['order_id']);assert 'cost_cents' not in row and row['details']['order_ref']=='00003'
        before=host.service.ledger.inventory();entry=host.service.backup(kind='maintenance');target=host.root/'native-restored'
        ledger,auth=restore(entry['service_bundle'],target,'manager','new-smoke-password-123')
        assert ledger.backend=='rust' and ledger.inventory()==before
        assert ledger.query_request(recovered['request_id'],host.admin)['order_id']==recovered['order_id']
        try:auth.authenticate(sales.token)
        except APIError:pass
        else:raise AssertionError('old session survived restore')
        result=dict(status='passed',backend='rust',DPAPI_encrypted_native_unknown_commit_and_receipt_recovery=True,
            actual_HTTPS_unmodified_client=True,role_projection_and_text_identity=True,backup_v3_independent_native_restore_equal=True,
            old_sessions_removed_on_restore=True,inventory=before,
            host_private_directory_native_security=host.config['private_security'],
            scope='Windows temp host/native Rust processes/HTTPS/DPAPI/backup restore; no GUI, installed service, real E/share or production switch')
    finally:host.close()
    result['sandbox_cleaned']=True;return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--windows-smoke',action='store_true');mode.add_argument('--checks-only',action='store_true');p.add_argument('--output',required=True)
    args=p.parse_args(argv);output=new_output(args.output)
    report=dict(task='P06-02',status='running',environment=dict(os=platform.system(),python=platform.python_version()),source_commit=None,implementation_sha256_LF=None,commands=[],checks=None,shadow_comparison=None,native_smoke=None,production_paths_accessed=False,production_writer_replaced=False,Windows_acceptance='pending')
    try:
        if args.windows_smoke and (os.name!='nt' or platform.system()!='Windows'):raise RuntimeError('ACTUAL_WINDOWS_REQUIRED')
        report['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,encoding='utf-8').strip()
        report['worktree_dirty']=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True,encoding='utf-8').strip())
        report['implementation_sha256_LF']=fingerprints();cargo=shutil.which('cargo');rustc=shutil.which('rustc')
        if not cargo or not rustc:raise RuntimeError('RUST_1_97_1_MSVC_BUILD_TOOLS_REQUIRED')
        version=run([rustc,'+1.97.1','-vV']);report['commands'].append(version)
        if version['exit_code'] or not version['stdout'].startswith('rustc 1.97.1 '):raise RuntimeError('PINNED_TOOLCHAIN_REQUIRED')
        if args.windows_smoke and 'host: x86_64-pc-windows-msvc' not in version['stdout']:raise RuntimeError('NATIVE_MSVC_HOST_REQUIRED')
        report['environment']['rustc']=version['stdout'].strip()
        for tail in [['fmt','--all','--','--check'],['clippy','--locked','--workspace','--all-targets','--','-D','warnings'],['test','--locked','--workspace'],['build','--locked','--release','--workspace']]:
            record=run([cargo,'+1.97.1',*tail]);report['commands'].append(record)
            if record['exit_code']:raise RuntimeError('RUST_CHECK_FAILED')
        meta=run([cargo,'+1.97.1','metadata','--locked','--format-version','1'])
        if meta['exit_code']:raise RuntimeError('DEPENDENCY_METADATA_FAILED')
        packages=json.loads(meta['stdout'])['packages'];external=[dict(name=v['name'],version=v['version'],license=v['license']) for v in packages if v['source'] is not None]
        expected=json.loads((ROOT/'docs/verification/P06-02-dependencies.json').read_text(encoding='utf-8'))['packages']
        if {(v['name'],v['version'],v['license']) for v in external}!={(v['name'],v['version'],v['license']) for v in expected}:raise RuntimeError('DEPENDENCY_LICENSE_MISMATCH')
        report['dependencies']=external
        from p05_service_check import dependencies
        report['service_dependencies']=dependencies()
        if any(v['status']!='available' for v in report['service_dependencies']):raise RuntimeError('EXISTING_PINNED_SERVICE_DEPENDENCIES_REQUIRED')
        report['checks']=run_checks()
        binary=ROOT/'target/release'/('quote-shadow.exe' if os.name=='nt' else 'quote-shadow')
        report['shadow_comparison']=compare(binary,output)
        worker=ROOT/'target/release'/('quote-ledger.exe' if os.name=='nt' else 'quote-ledger');report['worker_sha256']=hashlib.sha256(worker.read_bytes()).hexdigest()
        if report['checks']['status']!='passed' or report['shadow_comparison']['status']!='passed':raise RuntimeError('FUNCTIONAL_CHECK_FAILED')
        if args.windows_smoke:report['native_smoke']=windows_smoke();report['Windows_acceptance']='isolated_native_ledger_protocol_backup_passed_user_acceptance_pending'
        report['status']='Windows_native_ledger_service_passed_acceptance_pending' if args.windows_smoke else 'auxiliary_native_ledger_service_passed_Windows_pending'
    except Exception as e:report['status']='failed';report['failure']=dict(reason=str(e),traceback=traceback.format_exc())
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary={k:report[k] for k in ['task','status','environment','Windows_acceptance','production_paths_accessed','production_writer_replaced','native_smoke']}
    for key in ['checks','shadow_comparison']:
        v=report[key];summary[key]=None if v is None else {k:x for k,x in v.items() if k not in ['log','test_ids']}
    if 'failure' in report:summary['failure']=report['failure']['reason']
    summary['report_path']=str(output/'report.json');print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0 if report['status'] in ['Windows_native_ledger_service_passed_acceptance_pending','auxiliary_native_ledger_service_passed_Windows_pending'] else 1
if __name__=='__main__':raise SystemExit(main())
