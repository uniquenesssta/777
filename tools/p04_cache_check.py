"""P04-02 temporary incremental read checks and optional actual Windows Tk."""
import argparse
import hashlib
import io
import platform
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(ROOT/'tests')]
from p03_format_check import case_ids
import p04_io_check as background
import p01_fixtures as fixtures


def run_checks():
    suite=unittest.defaultTestLoader.loadTestsFromName('test_incremental_reads')
    ids=list(case_ids(suite));log=io.StringIO();start=time.monotonic()
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    return {'status':'passed' if result.wasSuccessful() else 'failed','tests_run':result.testsRun,
        'failures':len(result.failures),'errors':len(result.errors),'skipped':result.skipped,
        'elapsed_seconds':round(time.monotonic()-start,3),'test_ids':ids,'log':log.getvalue()}


def cache_steps(manager,sales,sandbox,report,await_task):
    report['active_step']='P04-02: cold/warm directory index'
    yield lambda:not manager._io_callbacks and not sales._io_callbacks
    extras=[]
    for index,rows in enumerate((20,40,20)):
        path=sandbox/'reports'/f'P04-cache-{index}.xlsx';fixtures.workbook(path,rows);extras.append(path)
    manager._ledger_cache.clear()
    before=manager._ledger_cache.metrics().get('workbook_opens',0)
    yield from await_task(manager,manager.refresh_excel_files())
    yield lambda:not manager._io_callbacks
    cold=manager._ledger_cache.metrics();cold_opens=cold.get('workbook_opens',0)-before
    assert cold_opens==4,(cold_opens,cold)
    before=cold.get('workbook_opens',0)
    yield from await_task(manager,manager.aggregate_all_excels(silent=True))
    yield lambda:not manager._io_callbacks
    warm=manager._ledger_cache.metrics();assert warm.get('workbook_opens',0)==before
    assert manager.excel_total_income.get()=='824.00'
    assert manager.excel_total_cost.get()=='328.00'
    report['checks']['cache_cold_four_files_warm_zero_decode_and_exact_amounts']='passed'
    report['cache_profile']={'scope':'Temporary local synthetic 20/40-row files and current windows; cache read counters exclude required transaction/CAS reads, not P04-04 SMB performance',
        'cold_workbook_opens':cold_opens,'warm_workbook_opens':0,'cold_metrics':cold,'warm_metrics':warm}
    report['active_step']='P04-02: reusable manager/sales file views'
    before=manager._ledger_cache.metrics().get('workbook_opens',0)
    yield from await_task(manager,manager.open_excel_path(str(extras[1])))
    assert manager._ledger_cache.metrics().get('workbook_opens',0)==before
    sales._ledger_cache.clear()
    yield from await_task(sales,sales.open_excel_path(str(extras[1])))
    before=sales._ledger_cache.metrics().get('workbook_opens',0)
    yield from await_task(sales,sales.load_current_excel_sheet())
    assert sales._ledger_cache.metrics().get('workbook_opens',0)==before
    assert len(sales.excel_view_tree.get_children())==40
    report['checks']['cache_reused_file_views_and_sales_forty_rows']='passed'
    report['active_step']='P04-02: external file change/deletion'
    before=manager._ledger_cache.metrics().get('workbook_opens',0)
    fixtures.workbook(extras[0],21)
    yield from await_task(manager,manager.refresh_excel_files())
    yield lambda:not manager._io_callbacks
    assert manager._ledger_cache.metrics().get('workbook_opens',0)-before==1
    assert manager.excel_total_income.get()=='834.00'
    assert manager.excel_read_results.aggregate['changed_files']==1
    before=manager._ledger_cache.metrics().get('workbook_opens',0);extras[0].unlink()
    yield from await_task(manager,manager.refresh_excel_files())
    yield lambda:not manager._io_callbacks
    assert manager._ledger_cache.metrics().get('workbook_opens',0)==before
    assert manager.excel_total_income.get()=='624.00'
    report['checks']['cache_external_change_one_decode_delete_zero_decode']='passed'
    report['active_step']='P04-02: target write invalidation'
    actual=Path(manager.last_file_transaction.path)
    yield from await_task(manager,manager.open_excel_path(str(actual)))
    manager.excel_view_tree.selection_set('row_7');manager.load_current_excel_remark()
    before=manager._ledger_cache.metrics().get('workbook_opens',0)
    manager.excel_remark_text.insert('1.0','缓存增量备注（合成）')
    yield from await_task(manager,background.invoke_write_control(manager,manager.excel_note_button))
    yield lambda:not manager._io_callbacks
    assert manager._ledger_cache.metrics().get('workbook_opens',0)-before==1
    assert manager.excel_total_income.get()=='624.00'
    report['checks']['cache_actual_note_write_reloads_only_target']='passed'
    report['cache_profile']['after_mutations']=manager._ledger_cache.metrics()


def run_gui():return background.run_gui(extra_steps=cache_steps)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gui-smoke',action='store_true');p.add_argument('--output',type=Path)
    args=p.parse_args(argv);checks=run_checks()
    paths=sorted([*ROOT.glob('quote_app/*.py'),*ROOT.glob('quote_files/*.py'),*ROOT.glob('报价*.py'),
        ROOT/'tests/test_incremental_reads.py',ROOT/'tests/test_background_io.py',ROOT/'tests/test_ledger_reading.py',
        ROOT/'tools/p02_gui_check.py',ROOT/'tools/p04_io_check.py',Path(__file__)])
    report={'task':'P04-02','commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'environment':{'os':platform.system(),'python':platform.python_version()},'checks':checks,
        'implementation_sha256_LF':{f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for f in paths},
        'production_paths_accessed':False,'scope':'Temporary synthetic ledger files, parse counts, invalidation and optional actual Windows Tk',
        'windows_gui':'not_requested','status':checks['status']}
    if args.gui_smoke:
        if platform.system()!='Windows':report.update(status='blocked' if checks['status']=='passed' else 'failed',windows_gui='blocked: Windows GUI only')
        elif checks['status']=='passed':
            try:report['windows_gui']=run_gui();report['status']=report['windows_gui']['status']
            except Exception as exc:report.update(status='failed',windows_gui={'status':'failed','error':f'{type(exc).__name__}: {exc}'})
        else:report['windows_gui']='not_run: incremental checks failed'
    from baseline_check import emit
    emit(report,args.output)
    return 2 if report['status']=='blocked' else int(report['status']=='failed')


if __name__=='__main__':raise SystemExit(main())
