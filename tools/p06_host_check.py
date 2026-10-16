"""P06-04 standalone Rust host, original Windows clients and resource evidence."""
import argparse,hashlib,io,json,os,platform,shutil,subprocess,sys,traceback,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(ROOT/'tests')]
from p01_validation import new_output
from p03_format_check import case_ids
from p06_excel_check import fingerprints as excel_fingerprints
from p06_core_check import run,compare
MODULES=['test_native_host','test_p06_host_check','test_ledger_security','test_native_excel','test_p06_excel_check','test_rust_ledger','test_rust_service','test_p06_ledger_check','test_service_outputs','test_legacy_import','test_p05_import_entry']
def fingerprints():
    result=excel_fingerprints()
    names=['tools/p06_host_check.py','tools/p06_resources.py','tools/p06_reference_host.py','tools/p06_ci_fonts.py','tools/p05_service_check.py','tests/native_host_fixture.py','tests/test_native_host.py','tests/test_p06_host_check.py','tests/test_ledger_security.py','docs/verification/P06-04-protocol.json','docs/verification/P06-04-dependencies.json','docs/verification/P06-04-auth-schema.sql','docs/verification/P06-04-output-schema.sql','.github/workflows/p06-windows.yml']
    names += [p.relative_to(ROOT).as_posix() for p in (ROOT/'crates/quote-host').rglob('*.json')]
    for name in names:result[name]=hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    return dict(sorted(result.items()))
def actual_windows():
    if os.name!='nt' or platform.system()!='Windows':raise RuntimeError('ACTUAL_WINDOWS_REQUIRED')
def run_checks():
    suite=unittest.defaultTestLoader.loadTestsFromNames(MODULES);ids=list(case_ids(suite));log=io.StringIO();r=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    return dict(status='passed' if r.wasSuccessful() else 'failed',tests_run=r.testsRun,failures=len(r.failures),errors=len(r.errors),skipped=r.skipped,test_ids=ids,log=log.getvalue(),failure_details=[dict(test_id=c.id(),error=t.strip().splitlines()[-1]) for c,t in r.failures+r.errors])
def protocol_smoke(*,windows):
    if windows:actual_windows()
    from native_host_fixture import Hosted,command,backup_pair,restore_data_backup
    from quote_core import QuoteSnapshot,NormalLine,DraftDetails
    from quote_service.client import CommitUnknown
    from quote_service.journal import Journal,MemoryJournal
    from quote_service.recovery import manifest
    from import_fixture import current_book,append_note_and_void
    from quote_import import preview_bytes,apply_source
    from quote_files.transactions import file_lock
    import base64,time
    from openpyxl import load_workbook
    host=Hosted();out={}
    try:
        sales=host.client();manager=host.client('manager');owner=sales.subject
        source=current_book(host.root/'historical-synthetic.xlsx');append_note_and_void(source);raw=source.read_bytes();mtime=source.stat().st_mtime_ns
        host.stop()
        with file_lock(host.host_root/'service-owner'):
            plan=preview_bytes(raw,'xlsx',native=host.service.ledger);assert plan.payload()==preview_bytes(raw,'xlsx').payload()
            imported=apply_source(host.service.ledger,host.admin,owner,raw,'xlsx',expected_review_sha256=plan.review_sha256)
            assert apply_source(host.service.ledger,host.admin,owner,raw,'xlsx',expected_review_sha256=plan.review_sha256)==imported
        host.start();journal=Journal(host.root/'pending.dat') if windows else MemoryJournal();host.fault.write_text('after_commit',encoding='utf-8')
        try:sales.submit(QuoteSnapshot('fixture-v1',(NormalLine('单件','4'),)),DraftDetails('=中文','00003','微信'),journal)
        except CommitUnknown:pass
        else:raise AssertionError('NATIVE_COMMIT_UNKNOWN_NOT_REPRODUCED')
        assert journal.read() is not None
        if windows:assert b'00003' not in journal.path.read_bytes()
        host.restart();order=sales.check_pending(journal)['result'];assert journal.read() is None and order['income_cents']=='4000'
        public=host.root/'public';public.mkdir()
        with host.service.auth.connection() as c:c.execute('UPDATE preferences SET export_dir=?,image_dir=?,revision=revision+1 WHERE id=1',(str(public),str(public)))
        tasks=[];contents=[]
        for api,kind in [(sales,'excel_quote'),(manager,'excel_admin')]+([(sales,'quote_png')] if windows or host.font else []):
            task=api.mutate('/v1/outputs',dict(order_id=order['order_id'],expected_revision=1,kind=kind),Journal(host.root/(kind+'.pending')) if windows else MemoryJournal())
            deadline=time.monotonic()+30
            while True:
                state=api.request('GET','/v1/outputs/'+task['job_id'])
                if state['state']=='done':break
                if state['state']=='failed' or time.monotonic()>deadline:raise RuntimeError('NATIVE_OUTPUT_NOT_DONE:'+str(state.get('error')))
                time.sleep(.02)
            content=api.request('GET','/v1/outputs/'+task['job_id']+'/content');data=base64.b64decode(content['data_base64'],validate=True);assert hashlib.sha256(data).hexdigest()==content['sha256']
            if kind.startswith('excel_'):
                book=load_workbook(io.BytesIO(data))
                try:
                    fields=dict(list(book['Order'].values)[1:]);assert fields['order_ref']=='00003' and fields['income_cents']=='4000';assert ('cost_cents' in fields)==(kind=='excel_admin');assert all(w.freeze_panes=='A2' and all(c.font.bold for c in w[1]) for w in book);assert all(c.number_format=='@' and c.data_type!='f' for w in book for row in w for c in row)
                finally:book.close()
            else:
                from PIL import Image
                with Image.open(io.BytesIO(data)) as image:assert image.format=='PNG' and image.width==1200 and image.info['777_job_id']==task['job_id'] and image.info['777_format']=='777-output-v1';image.verify()
            filename='777-'+order['order_id']+'-'+task['job_id']+('.png' if kind=='quote_png' else '.xlsx')
            if kind=='excel_admin':
                from quote_service.protocol import APIError
                try:sales.request('GET','/v1/outputs/'+task['job_id']+'/content')
                except APIError as exc:assert exc.status in (403,404)
                else:raise AssertionError('COST_OUTPUT_LEAK')
                assert not (public/filename).exists()
            else:assert (public/filename).read_bytes()==data
            tasks.append(task);contents.append(content)
        inventory=host.service.ledger.inventory();assert inventory['counts']==dict(orders=3,lines=4,notes=1,price_versions=2,import_batches=1,requests=7,audit_events=7);assert [inventory[k] for k in ['active_income_cents','active_cost_cents','active_profit_cents']]==['11500','4600','6900']
        backup=manager.request('POST','/v1/backup',{'kind':'daily'});folder=backup_pair(host,backup);assert json.loads((folder/'data.qbackup').read_bytes())['format']=='777-data-backup-v1'
        host.stop();restored=host.root/'native-restored';new_secret='isolated-new-password-123';restoration=restore_data_backup(host,backup,restored,password=new_secret);assert restoration['inventory']==inventory
        from quote_service.hosting import load
        _,_,checked=load(restored,auxiliary=not windows);assert checked.ledger.inventory()==inventory
        with checked.auth.connection() as c:assert c.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
        assert checked.ledger.query_request(imported['request_id'],host.admin)==imported
        for task,content in zip(tasks,contents):assert checked.outputs.content(host.admin,task['job_id'])==content
        host.host_root=restored;host.password=new_secret;host.config=json.loads((restored/'private/service.json').read_bytes());host.fault=restored/'private/test-fault.txt';host.start();new_manager=host.client('recovered-manager');assert new_manager.request('GET','/v1/orders')['total']==3
        try:sales.request('GET','/v1/me')
        except APIError as e:assert e.status in (401,403)
        else:raise AssertionError('OLD_SESSION_SURVIVED')
        assert source.read_bytes()==raw and source.stat().st_mtime_ns==mtime
        out=dict(status='passed',host_backend='standalone-rust',runtime_python_server_used=False,in_process_ledger_and_formats=True,actual_HTTPS_old_Client=True,native_host_exit_and_original_receipt_recovery=True,DPAPI_encrypted_pending_verified=windows,offline_historical_tool_import_plan_and_idempotency_preserved=True,source_hash_and_mtime_unchanged=True,independent_reader_excel_text_styles_and_private_cost=True,native_CJK_PNG_and_independent_Pillow_verified=bool(windows or host.font),Windows_system_CJK_font_verified=bool(windows and not host.font),public_directory_only_quote_outputs=True,v1_logical_data_restore_and_original_receipts_outputs_equal=True,independent_Python_ledger_reader_equal=True,restored_new_root_and_fresh_credentials=True,old_sessions_removed_on_restore=True,restored_Rust_HTTPS_accepts_old_client=True,inventory=inventory,host_private_directory_native_security=host.config['private_security'],scope='isolated Rust host processes, old API Client, offline synthetic migration tools and native logical data restore; no installed service, real E/share paths or production activation')
    finally:host.close()
    out['sandbox_cleaned']=True;return out

def windows_smoke():
    actual_windows()
    from native_host_fixture import Hosted
    import service_fixture,p05_service_check
    host=Hosted();manager=host.client('manager')
    # Reuse the accepted original Tk verification without changing either app.
    # Its backup callback invokes the real Rust HTTPS endpoint in this fixture.
    host.service.backup=lambda **kw:manager.request('POST','/v1/backup',{'kind':kw.get('kind','rolling')})
    with patch.object(service_fixture,'Hosted',return_value=host):gui=p05_service_check.windows_smoke()
    gui['host_backend']='standalone-rust';gui['runtime_Python_ASGI_server_used']=False
    return {'original_Windows_Tk_clients':gui,'native_protocol_and_restore':protocol_smoke(windows=True)}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument('--windows-smoke',action='store_true');mode.add_argument('--ci-checks',action='store_true');mode.add_argument('--checks-only',action='store_true');parser.add_argument('--output',required=True);parser.add_argument('--font-fixture',type=Path);args=parser.parse_args(argv);output=new_output(args.output)
    r=dict(task='P06-04',status='running',environment=dict(os=platform.system(),python=platform.python_version()),source_commit=None,implementation_sha256_LF=None,commands=[],checks=None,shadow_comparison=None,native_smoke=None,resource_comparison=None,production_paths_accessed=False,production_writer_replaced=False,Windows_acceptance='pending')
    try:
        if args.windows_smoke or args.ci_checks:actual_windows()
        if args.windows_smoke and (args.font_fixture or os.environ.get('P06_CI_FONT_FILE')):raise RuntimeError('ACTUAL_WINDOWS_FONT_CONTEXT_REQUIRED')
        r['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,encoding='utf-8').strip();r['worktree_dirty']=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True,encoding='utf-8').strip());r['implementation_sha256_LF']=fingerprints()
        cargo=shutil.which('cargo');rustc=shutil.which('rustc')
        if not cargo or not rustc:raise RuntimeError('PINNED_RUST_AND_MSVC_REQUIRED')
        v=run([rustc,'+1.97.1','-vV']);r['commands'].append(v);r['environment']['rustc']=v['stdout'].strip()
        if v['exit_code'] or not v['stdout'].startswith('rustc 1.97.1 '):raise RuntimeError('PINNED_TOOLCHAIN_REQUIRED')
        if (args.windows_smoke or args.ci_checks) and 'host: x86_64-pc-windows-msvc' not in v['stdout']:raise RuntimeError('NATIVE_MSVC_REQUIRED')
        for tail in [['fmt','--all','--','--check'],['clippy','--locked','--workspace','--all-targets','--','-D','warnings'],['test','--locked','--workspace'],['build','--locked','--release','--workspace']]:
            c=run([cargo,'+1.97.1',*tail]);r['commands'].append(c)
            if c['exit_code']:raise RuntimeError('RUST_CHECK_FAILED')
        meta=run([cargo,'+1.97.1','metadata','--locked','--format-version','1']);packages=json.loads(meta['stdout'])['packages'];r['dependencies']=[dict(name=p['name'],version=p['version'],license=p['license']) for p in packages if p['source'] is not None];manifest=json.loads((ROOT/'docs/verification/P06-04-dependencies.json').read_text(encoding='utf-8'))['packages'];triples=lambda a:{(v['name'],v['version'],v['license']) for v in a}
        if triples(r['dependencies'])!=triples(manifest):raise RuntimeError('DEPENDENCY_LICENSE_MISMATCH')
        from p05_service_check import dependencies
        r['service_dependencies']=dependencies()
        if any(p['status']!='available' for p in r['service_dependencies']):raise RuntimeError('PINNED_REFERENCE_DEPENDENCIES_REQUIRED')
        font_file=None
        if args.font_fixture:
            from p06_ci_fonts import SHA
            font_file=args.font_fixture/'NotoSansSC-VF.ttf'
            if not (args.ci_checks or args.checks_only) or hashlib.sha256(font_file.read_bytes()).hexdigest()!=SHA:raise RuntimeError('CI_FONT_CONTEXT_INVALID')
            r['verification_font_context']=json.loads((args.font_fixture/'provenance.json').read_text(encoding='utf-8'))
            os.environ['P06_CI_FONT_FILE']=str(font_file.resolve())
        from contextlib import nullcontext
        from quote_service import output_render
        from PIL import ImageFont
        with patch.object(output_render,'_cjk_font',side_effect=lambda:ImageFont.truetype(str(font_file),24)) if font_file else nullcontext():
            r['checks']=run_checks()
        import legacy_worker_fixture;r['legacy_worker_build']=legacy_worker_fixture.build_record
        r['shadow_comparison']=compare(ROOT/'target/release'/('quote-shadow.exe' if os.name=='nt' else 'quote-shadow'),output)
        if r['checks']['status']!='passed' or r['checks']['skipped'] or r['shadow_comparison']['status']!='passed':raise RuntimeError('CONTRACT_CHECK_FAILED')
        r['worker_sha256']=hashlib.sha256((ROOT/'target/release'/('quote-ledger.exe' if os.name=='nt' else 'quote-ledger')).read_bytes()).hexdigest();r['host_sha256']=hashlib.sha256((ROOT/'target/release'/('quote-host.exe' if os.name=='nt' else 'quote-host')).read_bytes()).hexdigest()
        if args.windows_smoke:r['native_smoke']=windows_smoke();r['Windows_acceptance']='isolated_Rust_host_original_Windows_GUI_and_native_restore_passed_user_acceptance_pending'
        elif args.ci_checks:r['native_smoke']=protocol_smoke(windows=True);r['Windows_acceptance']='Windows_CI_native_protocol_passed_original_GUI_and_user_acceptance_pending'
        else:r['native_smoke']=protocol_smoke(windows=False);r['Windows_acceptance']='pending_actual_Windows_GUI_DPAPI_ACL_PNG_and_resources'
        from p06_resources import compare as resources
        r['resource_comparison']=resources();r['status']='Windows_Rust_host_passed_acceptance_pending' if args.windows_smoke else 'Windows_CI_native_host_passed_GUI_pending' if args.ci_checks else 'auxiliary_Rust_host_contracts_passed_actual_Windows_pending'
    except Exception as exc:r['status']='failed';r['failure']=type(exc).__name__+': '+str(exc);r['failure_traceback']=traceback.format_exc()
    (output/'report.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in r.items() if k not in {'implementation_sha256_LF','commands','checks','failure_traceback','dependencies','legacy_worker_build'}},ensure_ascii=False,indent=2));return 0 if r['status']!='failed' else 1
if __name__=='__main__':raise SystemExit(main())
