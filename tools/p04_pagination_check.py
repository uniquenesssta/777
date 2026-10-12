"""P04-03 synthetic complete pagination/attachments and actual Windows Tk checks."""
import argparse
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
from threading import Event
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(ROOT/'tests')]
from p03_format_check import case_ids
import p04_io_check as background
from p04_cache_check import cache_steps
import p01_fixtures as fixtures


def run_checks():
    suite=unittest.defaultTestLoader.loadTestsFromName('test_pagination_images')
    ids=list(case_ids(suite));log=io.StringIO();start=time.monotonic()
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    return {'status':'passed' if result.wasSuccessful() else 'failed','tests_run':result.testsRun,
        'failures':len(result.failures),'errors':len(result.errors),'skipped':result.skipped,
        'elapsed_seconds':round(time.monotonic()-start,3),'test_ids':ids,'log':log.getvalue()}


def make_tail_fixture(app,path):
    """Synthetic stable 401-line order written by the existing pure controller."""
    from quote_app.background import controller,capture
    from quote_core import QuoteSession
    class Context:
        def check(self):pass
        def progress(self,*_):pass
    snapshot=capture(app)
    def build():
        worker=controller(type(app),snapshot,Context())
        state=worker.quote_session.state
        session=QuoteSession(replace(state.snapshot,lines=tuple(state.snapshot.lines[0] for _ in range(401))),
            state.prices,details=state.details,price_source='current',latest_price_version_id=state.prices.price_version_id)
        session.calculate();worker._excel_pending=None;worker.get_daily_excel_path=lambda:str(path)
        worker._write_quote_excel(session.prepare_output('excel').payload)
    return build


def pagination_steps(manager,sales,sandbox,report,await_task,*,native_capture=True):
    from quote_app.pagination import PAGE_SIZE
    from quote_files.reading import read_ledger
    from PIL import Image
    from quote_files.quote_images import chinese_font
    report['quote_image_font']=str(chinese_font().path)
    yield from cache_steps(manager,sales,sandbox,report,await_task)
    report['active_step']='P04-03: construct synthetic large files'
    large=sandbox/'reports'/'P04-10000明细.xlsx';tail=sandbox/'reports'/'P04-401稳定明细.xlsx'
    tail_builder=make_tail_fixture(manager,tail);finished=Event();problems=[]
    def build():
        try:fixtures.workbook(large,10000);tail_builder()
        except Exception as exc:problems.append(exc)
        finally:finished.set()
    task=manager._io_runtime.submit('diagnostic_fixture',lambda context:build(),write=True)
    yield finished.is_set
    yield lambda:task.state in {'completed','failed'}
    assert task.state=='completed'
    if problems:raise problems[0]
    report['active_step']='P04-03: complete actual Treeview pages'
    counts={}
    for app in (manager,sales):
        yield from await_task(app,app.open_excel_path(str(large)))
        seen=[]
        while True:
            seen.extend(app.excel_view_row_map.values())
            assert len(app.excel_view_tree.get_children())<=PAGE_SIZE
            if (app._page_number+1)*PAGE_SIZE>=len(app._page_indices):break
            assert str(app.excel_next_button.cget('state'))!='disabled'
            app.excel_next_button.invoke()
            # Let the real event loop draw each bounded page and selection.
            yield lambda:True
        assert len(seen)==len(set(seen))==(10006 if app.quote_role=='manager' else 10000)
        assert 10006 in seen and app._page_view.ledger.totals.income_cents==10000000
        counts[app.quote_role]={'visible_rows':len(seen),'detail_rows':app._page_view.ledger.detail_count,'pages':app._page_number+1,'page_size':PAGE_SIZE}
    report['checks']['pagination_ten_thousand_actual_rows_reachable_both_roles']='passed'
    report['pagination_profile']=counts
    report['active_step']='P04-03: filter/jump/saved position'
    sales.excel_filter_var.set('合成订单009999');previous=sales._io_runtime.latest.get('view')
    sales.excel_filter_button.invoke();task=sales._io_runtime.latest.get('view');assert task is not previous
    yield from await_task(sales,task)
    assert list(sales.excel_view_row_map.values())==[10006]
    yield from await_task(sales,sales.clear_excel_filter())
    sales.excel_page_var.set('25');sales.excel_jump_button.invoke();assert sales._page_number==24
    selected=next(iter(sales.excel_view_row_map));sales.excel_view_tree.selection_set(selected)
    before_scroll=sales.excel_view_tree.yview()[0]
    yield from await_task(sales,sales.open_excel_path(str(tail)))
    yield from await_task(sales,sales.open_excel_path(str(large)))
    assert sales._page_number==24 and sales.excel_view_tree.selection()==(selected,)
    assert abs(sales.excel_view_tree.yview()[0]-before_scroll)<.01
    report['checks']['pagination_filter_jump_and_file_return_keep_position']='passed'
    report['active_step']='P04-03: manager edits a stable order after row 300'
    yield from await_task(manager,manager.open_excel_path(str(tail)))
    manager.excel_next_button.invoke();manager.excel_view_tree.selection_set('row_350');manager.load_current_excel_remark()
    old=read_ledger(tail).totals;order=manager._excel_view_orders[350][0]
    manager.excel_remark_text.insert('1.0','分页后段合成备注')
    yield from await_task(manager,background.invoke_write_control(manager,manager.excel_note_button))
    yield lambda:not manager._io_callbacks
    assert manager._page_number==1 and manager.excel_view_tree.selection()==('row_350',)
    assert read_ledger(tail).totals==old and any('分页后段合成备注' in text for _,text in manager._excel_order_views[order].notes)
    report['checks']['pagination_tail_order_note_preserves_selection_and_money']='passed'
    report['active_step']='P04-03: actual complete quote image controls'
    original=Path(sales.last_file_transaction.path);original_bytes=original.read_bytes()
    for _ in range(41):manager.add_calc_row('完整报价图合成项目','P02面积',False)
    yield from await_task(manager,manager.calculate(notify=False))
    yield from await_task(manager,manager.confirm_current_prices())
    attachments={};complete_manifests={}
    for app in (manager,sales):
        yield from await_task(app,background.invoke_write_control(app,app.calc_quote_image_button))
        manifest_path=Path(app.last_file_transaction.path);manifest=json.loads(manifest_path.read_text())
        assert manifest['line_count']==len(app.quote_session.state.result.lines)
        assert manifest['totals']['销售额']==app.quote_session.state.result.totals.display()['income']
        covered=[]
        for page in manifest['pages']:
            covered.extend(range(page['first_line'],page['last_line']+1))
            with Image.open(manifest_path.parent/page['file']) as image:
                assert image.height<=2400 and image.info['777_attachment_kind']=='complete_quote';image.verify()
        assert covered==list(range(1,manifest['line_count']+1))
        if app.quote_role=='sales':assert set(manifest['totals'])=={'销售额'}
        complete_manifests[app.quote_role]=manifest_path
        attachments[app.quote_role]={'line_count':manifest['line_count'],'pages':len(manifest['pages']),'all_rows_covered':True}
    assert original.read_bytes()==original_bytes and attachments['manager']['pages']>=2
    report['checks']['complete_quote_images_actual_buttons_all_lines_exact_totals']='passed'
    report['attachment_profile']=attachments
    if not native_capture:
        report['window_capture_profile']='not_run: auxiliary preflight has no actual Tk/HWND'
        return
    report['active_step']='P04-03: synthetic window HWND client capture'
    import tkinter as tk
    from quote_app.window_capture import native_window_id,capture_window
    marker=tk.Label(manager.root,text='合成窗口截图核验',background='#12ab34');marker.place(x=20,y=20,width=250,height=60)
    manager.root.lift()
    yield lambda:True
    previous=manager._io_runtime.latest.get('write');manager.calc_screenshot_button.invoke()
    yield lambda:manager._io_runtime.latest.get('write') is not previous
    task=manager._io_runtime.latest['write'];yield from await_task(manager,task)
    with Image.open(manager.last_file_transaction.path) as image:
        colors=image.getcolors(image.width*image.height) or []
        green=sum(n for n,color in colors if color[:3]==(18,171,52))
        assert green>50,green
        report['window_capture_profile']={'width_px':image.width,'height_px':image.height,'HWND':int(native_window_id(manager.root)),
            'tk_scaling':float(manager.root.tk.call('tk','scaling')),'synthetic_marker_pixels':green,
            'scope':'Current application window pixels via HWND; occlusion may affect a window screenshot. Complete quote images are data rendered and independent of window visibility/DPI. No desktop or production capture.'}
    overlay=tk.Toplevel(manager.root);overlay.configure(background='#fd02fc');overlay.geometry(manager.root.geometry());overlay.attributes('-topmost',True)
    try:
        yield lambda:True
        image=capture_window(manager.root)
        try:
            colors=image.getcolors(image.width*image.height) or []
            magenta=sum(n for n,color in colors if color[:3]==(253,2,252))
            report['window_capture_profile']['occlusion_color_pixels']=magenta
            report['window_capture_profile']['occlusion_observation']='overlay pixels observed' if magenta else 'no overlay pixels observed on this device/backend'
        finally:image.close()
        # The documented full-output option must remain pixel-identical while
        # the window is occluded; screen captures do not establish completeness.
        before_manifest=json.loads(complete_manifests['manager'].read_text())
        with Image.open(complete_manifests['manager'].parent/before_manifest['pages'][0]['file']) as first:
            before_pixels=hashlib.sha256(first.tobytes()).hexdigest()
        yield from await_task(manager,background.invoke_write_control(manager,manager.calc_quote_image_button))
        after_path=Path(manager.last_file_transaction.path);after_manifest=json.loads(after_path.read_text())
        with Image.open(after_path.parent/after_manifest['pages'][0]['file']) as first:
            after_pixels=hashlib.sha256(first.tobytes()).hexdigest()
        assert before_pixels==after_pixels
        report['window_capture_profile']['complete_quote_pixels_unchanged_under_occlusion']=True
    finally:overlay.destroy();marker.destroy()
    report['checks']['window_hwnd_capture_scope_and_occlusion_independent_complete_quote']='passed'


def run_gui():
    return background.run_gui(extra_steps=pagination_steps,scope='Actual Windows Tk, temporary synthetic local files, complete quote images and synthetic application HWND capture; no production share or desktop capture')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gui-smoke',action='store_true');p.add_argument('--output',type=Path)
    args=p.parse_args(argv);checks=run_checks()
    paths=sorted([*ROOT.glob('quote_app/*.py'),*ROOT.glob('quote_files/*.py'),*ROOT.glob('报价*.py'),
        ROOT/'tests/test_pagination_images.py',ROOT/'tests/test_application_integration.py',ROOT/'tests/test_background_io.py',
        ROOT/'tests/test_storage_configuration.py',ROOT/'tests/test_ledger_reading.py',ROOT/'tests/test_workbook_transactions.py',
        ROOT/'tools/p02_gui_check.py',ROOT/'tools/p04_io_check.py',ROOT/'tools/p04_cache_check.py',Path(__file__)])
    report={'task':'P04-03','commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'environment':{'os':platform.system(),'python':platform.python_version(),'pillow':__import__('PIL').__version__},'checks':checks,
        'implementation_sha256_LF':{f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for f in paths},
        'production_paths_accessed':False,'scope':'Temporary synthetic complete-pagination/image tests and optional actual Windows Tk/own synthetic HWND capture',
        'windows_gui':'not_requested','status':checks['status']}
    if args.gui_smoke:
        if platform.system()!='Windows':report.update(status='blocked' if checks['status']=='passed' else 'failed',windows_gui='blocked: Windows GUI only')
        elif checks['status']=='passed':
            try:report['windows_gui']=run_gui();report['status']=report['windows_gui']['status']
            except Exception as exc:report.update(status='failed',windows_gui={'status':'failed','error':f'{type(exc).__name__}: {exc}'})
        else:report['windows_gui']='not_run: pagination checks failed'
    from baseline_check import emit
    emit(report,args.output)
    return 2 if report['status']=='blocked' else int(report['status']=='failed')


if __name__=='__main__':raise SystemExit(main())
