"""Complete browsing and image attachments; synthetic files and Tcl only here."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import openpyxl
from PIL import Image
from test_application_integration import application
import p01_fixtures as fixtures
from test_background_io import asynchronous, wait_for, Tree
from test_workbook_transactions import export_one
from quote_app.pagination import PAGE_SIZE, filter_view
from quote_core import QuoteSession, QuoteSnapshot, NormalLine, DraftDetails
from quote_files.quote_images import quote_layout, quote_rows, render_page, save_quote_images, wrap_text
from quote_files.reading import read_ledger
from quote_files.views import read_view
from quote_files.transactions import FileFailure


class Context:
    def check(self):pass


def payload(count=41, role='manager', name='合成长名字'):
    from quote_core import PriceItem, PriceSnapshot
    prices=PriceSnapshot('synthetic-image', (PriceItem('商品','12.34','4.56','1',True),))
    session=QuoteSession(QuoteSnapshot(prices.price_version_id,tuple(NormalLine('商品',str(i+1),name=name) for i in range(count))),
                         prices,details=DraftDetails('中文客户'*10,'订单：001/测试','微信合成'),price_source='current',latest_price_version_id=prices.price_version_id)
    assert session.calculate().status=='valid'
    return session.prepare_output('quote_image').payload


class PageTree(Tree):
    def __init__(self):super().__init__();self.y=0;self.x=0
    def yview(self):return self.y,1
    def xview(self):return self.x,1
    def yview_moveto(self,n):self.y=n
    def xview_moveto(self,n):self.x=n
    def selection_remove(self,*_):self.selected=()
    def delete(self,*items):
        super().delete(*items)
        self.selected=tuple(i for i in self.selected if i in self.rows)


def page_controls(app):
    app.excel_view_tree=PageTree();app.excel_file_tree=PageTree()
    for key in ('excel_filter_var','excel_page_status','excel_page_var'):
        setattr(app,key,tk.StringVar(app.root,''))
    app.excel_prev_button=Mock();app.excel_next_button=Mock();app.excel_jump_button=Mock()


class PaginationTests(unittest.TestCase):
    def test_ten_thousand_rows_reachable_in_both_roles_no_duplicates_or_truncation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'完整.xlsx';fixtures.workbook(path,10000)
            for role in ('manager','sales'):
                with application(role) as (app, _, *_), asynchronous(app):
                    page_controls(app)
                    task=app.open_excel_path(str(path));wait_for(lambda:task.number not in app._io_callbacks,app._poll_io,seconds=12)
                    seen=[]
                    while True:
                        self.assertLessEqual(len(app.excel_view_tree.rows),PAGE_SIZE)
                        seen.extend(app.excel_view_row_map.values())
                        if (app._page_number+1)*PAGE_SIZE>=len(app._page_indices):break
                        app.change_excel_page(1)
                    self.assertEqual(len(seen),10006 if role=='manager' else 10000)
                    self.assertEqual(len(set(seen)),len(seen))
                    self.assertIn(10006,seen)
                    self.assertEqual(app._page_view.ledger.totals.income_cents,10000000)
                    self.assertIn('文件明细10000行',app.excel_page_status.get())

    def test_visible_columns_after_thirty_six_are_reachable_and_hidden_columns_stay_hidden(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'完整列.xlsx';fixtures.workbook(path,1)
            book=openpyxl.load_workbook(path);book.active.cell(2,50,'末列可达');book.active.column_dimensions['AW'].hidden=True;book.save(path);book.close()
            view=read_view(path,None,'manager',Context())
            self.assertIn('AX',view.headings);self.assertNotIn('AW',view.headings)
            self.assertIn('末列可达',view.rows[1][1])

    def test_search_keeps_original_row_ids_and_sales_does_not_search_cost_projection(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'筛选.xlsx';fixtures.workbook(path,450)
            view=read_view(path,None,'sales',Context())
            matches=filter_view(view,'合成订单000449')
            self.assertEqual([view.rows[i][0] for i in matches],[456])
            self.assertEqual(filter_view(view,'成本'),())
            self.assertEqual(view.ledger.detail_count,450)

    def test_page_file_switch_and_refresh_restore_selection_query_and_scroll(self):
        with application('sales') as (app,folder,*_),asynchronous(app):
            first=folder/'第一页.xlsx';other=folder/'另一个.xlsx';fixtures.workbook(first,450);fixtures.workbook(other,2)
            page_controls(app)
            def ready(task):wait_for(lambda:task.number not in app._io_callbacks,app._poll_io)
            ready(app.open_excel_path(str(first)));app.change_excel_page(1)
            app.excel_view_tree.selection_set('row_250');app.excel_view_tree.y=.37;app.excel_view_tree.x=.2
            ready(app.open_excel_path(str(other)));ready(app.open_excel_path(str(first)))
            self.assertEqual(app._page_number,1);self.assertEqual(app.excel_view_tree.selection(),('row_250',))
            self.assertEqual(app.excel_view_tree.y,.37);self.assertEqual(app.excel_view_tree.x,.2)
            app.excel_filter_var.set('合成订单000249');ready(app.filter_excel_view())
            self.assertEqual(list(app.excel_view_row_map.values()),[256])
            ready(app.load_current_excel_sheet());wait_for(lambda:not app._io_callbacks,app._poll_io)
            self.assertEqual(app._page_query,'合成订单000249');self.assertEqual(list(app.excel_view_row_map.values()),[256])

    def test_invalid_jump_and_empty_filter_are_explicit_without_changing_ledger(self):
        with application('sales') as (app,folder,*_),asynchronous(app):
            path=folder/'页码.xlsx';fixtures.workbook(path,3);page_controls(app)
            task=app.open_excel_path(str(path));wait_for(lambda:task.number not in app._io_callbacks,app._poll_io)
            for value in ('0','999','abc'):
                app.excel_page_var.set(value);self.assertFalse(app.jump_excel_page())
            app.excel_filter_var.set('不存在');task=app.filter_excel_view();wait_for(lambda:task.number not in app._io_callbacks,app._poll_io)
            self.assertEqual(app.excel_view_tree.get_children(),())
            self.assertIn('筛选0/3行',app.excel_page_status.get())
            self.assertEqual(app._page_view.ledger.totals.income_cents,3000)

    def test_selected_stable_order_filter_and_note_after_page_one_preserve_money(self):
        with application('manager') as (app,folder,*_):
            app.add_fixture_row(product='P02面积');app.calculate(notify=False)
            base=app.quote_session.state
            lines=tuple(base.snapshot.lines[0] for _ in range(401))
            app.quote_session=QuoteSession(replace(base.snapshot,lines=lines),base.prices,details=base.details,
                                          price_source='current',latest_price_version_id=base.prices.price_version_id)
            app.quote_session.calculate();path=Path(app._write_quote_excel(app.quote_session.prepare_output('excel').payload))
            with asynchronous(app):
                page_controls(app);task=app.open_excel_path(str(path));wait_for(lambda:task.number not in app._io_callbacks,app._poll_io,seconds=20)
                app.change_excel_page(1);app.excel_view_tree.selection_set('row_350')
                app.excel_remark_text=Mock();app.excel_remark_text.get.return_value='后段备注';app.excel_remark_text.configure=Mock()
                task=app.filter_selected_excel_order();wait_for(lambda:task.number not in app._io_callbacks,app._poll_io,seconds=20)
                self.assertEqual(len(app._page_indices),402)
                order=app._page_view.identities[350][0];app.select_excel_order(order)
                app._page_number=1;app._render_page();app.excel_view_tree.selection_set('row_350')
                before=read_ledger(path).totals
                task=app.save_current_excel_remark();wait_for(lambda:task.number not in app._io_callbacks,app._poll_io,seconds=20)
                wait_for(lambda:not app._io_callbacks,app._poll_io,seconds=20)
                self.assertEqual(read_ledger(path).totals,before)
                self.assertEqual(app._page_number,1)
                self.assertEqual(app.excel_view_tree.selection(),('row_350',))
                self.assertTrue(any('后段备注' in note for _,note in app._excel_order_views[order].notes))

    def test_file_list_refresh_preserves_selection_and_scroll(self):
        with application('manager') as (app,folder,*_),asynchronous(app):
            # Actual scan through explicit isolated storage setup.
            Path(app.report_dir).mkdir(exist_ok=True)
            for i in range(3):fixtures.workbook(Path(app.report_dir)/f'{i}.xlsx',1)
            page_controls(app);task=app.refresh_excel_files();wait_for(lambda:task.number not in app._io_callbacks,app._poll_io)
            path=app.excel_file_tree.get_children()[1];app.excel_file_tree.selection_set(path);app.excel_file_tree.y=.4
            task=app.refresh_excel_files();wait_for(lambda:task.number not in app._io_callbacks,app._poll_io)
            self.assertEqual(app.excel_file_tree.selection(),(path,));self.assertEqual(app.excel_file_tree.y,.4)

    def test_directory_reset_drops_old_page_locations_and_cancel_ignores_old_filter(self):
        with application('sales') as (app,folder,*_),asynchronous(app):
            path=folder/'取消.xlsx';fixtures.workbook(path,5);page_controls(app)
            task=app.open_excel_path(str(path));wait_for(lambda:task.number not in app._io_callbacks,app._poll_io)
            app._remember_page_location();self.assertTrue(app._page_locations)
            app.reset_excel_pagination();self.assertIsNone(app._page_view);self.assertEqual(app._page_locations,{})

    def test_cancelled_inflight_filter_does_not_publish_or_restart_work(self):
        from threading import Event
        import quote_app.pagination as paging
        with application('sales') as (app,folder,*_),asynchronous(app):
            path=folder/'取消筛选.xlsx';fixtures.workbook(path,3);page_controls(app)
            task=app.open_excel_path(str(path));wait_for(lambda:task.number not in app._io_callbacks,app._poll_io)
            rows=dict(app.excel_view_tree.rows);started,release=Event(),Event();original=paging.filter_view
            def slow(*args,**kwargs):started.set();release.wait(3);return original(*args,**kwargs)
            try:
                with patch.object(paging,'filter_view',side_effect=slow):
                    app.excel_filter_var.set('不存在');task=app.filter_excel_view();self.assertTrue(started.wait(1))
                    app.cancel_background_reads();release.set()
                    wait_for(lambda:not app._io_runtime.tasks,app._poll_io)
                self.assertEqual(app.excel_view_tree.rows,rows)
                self.assertEqual(app._page_query,'')
                self.assertEqual(app._io_runtime.latest['view'],task)
            finally:release.set()

    def test_windows_workflow_preflight_real_adapters_before_native_capture(self):
        from test_order_management import display
        import p04_pagination_check as check
        with application('manager') as (manager,folder,*_),application('sales') as (sales,*_):
            path=export_one(manager);manager.calculate(notify=False);manager.export_to_excel()
            display(manager,path)
            del manager.get_selected_excel_row_index
            del manager.load_current_excel_sheet
            sales.data_source_var.set(str(folder));self.assertTrue(sales.apply_connection())
            sales.add_fixture_row(product='P02面积');sales.calculate(notify=False)
            with asynchronous(manager),asynchronous(sales):
                page_controls(manager);page_controls(sales)
                for app in (manager,sales):
                    app.add_calc_row=lambda name,product,single,a=app:a.add_fixture_row(product=product)
                    app.show_price_changes=Mock()
                    app.calc_quote_image_button=Mock();app.calc_quote_image_button.cget.return_value='normal'
                    app.calc_quote_image_button.invoke=app.save_quote_image
                    app.excel_next_button.cget.side_effect=lambda _,a=app:'disabled' if (a._page_number+1)*PAGE_SIZE>=len(a._page_indices) else 'normal'
                    app.excel_next_button.invoke=lambda a=app:a.change_excel_page(1)
                    app.excel_jump_button.invoke=app.jump_excel_page
                    app.excel_filter_button=Mock();app.excel_filter_button.invoke=app.filter_excel_view
                manager.excel_note_button.cget.return_value='normal';manager.excel_note_button.invoke=manager.save_current_excel_remark
                sales.last_file_transaction=manager.last_file_transaction
                def await_task(app,task):
                    self.assertTrue(task);yield lambda:task.number not in app._io_callbacks
                report={'checks':{}}
                for ready in check.pagination_steps(manager,sales,folder,report,await_task,native_capture=False):
                    wait_for(ready,lambda:(manager._poll_io(),sales._poll_io()),seconds=20)
                self.assertEqual(len(report['checks']),8)
                self.assertEqual(set(report['checks'].values()),{'passed'})
                self.assertEqual(report['pagination_profile']['sales']['detail_rows'],10000)
                self.assertGreaterEqual(report['attachment_profile']['manager']['pages'],2)

    def test_windows_gui_entry_is_blocked_elsewhere_before_constructing_tk(self):
        import p04_pagination_check as check
        with patch.object(check,'run_checks',return_value={'status':'passed'}),patch.object(check.platform,'system',return_value='Linux'),patch.object(check,'run_gui') as gui,patch('baseline_check.emit'):
            self.assertEqual(check.main(['--gui-smoke']),2);gui.assert_not_called()


class QuoteImageTests(unittest.TestCase):
    def test_ten_thousand_lines_layout_complete_and_total_never_uses_a_page_subtotal(self):
        class Font:
            def getlength(self,text):return len(text)*11
            def getbbox(self,text):return 0,0,22,22
        p=payload(10000);layout=quote_layout(p,'sales',Font())
        indexes=[index for page in layout['pages'] for index,_,_ in page]
        self.assertEqual(indexes,list(range(1,10001)))
        self.assertTrue(all(len(page)<=40 for page in layout['pages']))
        self.assertEqual(layout['totals']['销售额'],p.result.totals.display()['income'])

    def test_sales_projection_and_manifest_never_include_cost_or_profit(self):
        p=payload(41);head,rows,totals=quote_rows(p,'sales')
        self.assertEqual(len(head),5);self.assertTrue(all(len(row)==5 for row in rows))
        self.assertEqual(set(totals),{'销售额'})
        with tempfile.TemporaryDirectory() as folder:
            result=save_quote_images(folder,p,'sales');manifest=json.loads(Path(result.manifest).read_text())
            self.assertEqual(manifest['line_count'],41)
            self.assertNotIn('成本',json.dumps(manifest,ensure_ascii=False));self.assertNotIn('利润',json.dumps(manifest,ensure_ascii=False))
            self.assertEqual(manifest['pages'][0]['first_line'],1)
            self.assertEqual(manifest['pages'][-1]['last_line'],41)
            for previous,current in zip(manifest['pages'],manifest['pages'][1:]):
                self.assertEqual(current['first_line'],previous['last_line']+1)
            for path in result.paths:
                with Image.open(path) as image:self.assertEqual(image.info['777_attachment_kind'],'complete_quote');image.verify()

    def test_long_chinese_names_wrapped_without_loss_and_no_page_exceeds_budget(self):
        p=payload(2,name='中文长商品名称'*35);layout=quote_layout(p,'manager')
        for page in layout['pages']:
            for index,cells,height in page:self.assertEqual(''.join(cells[1]),p.result.lines[index-1].raw.name)
        image=render_page(layout,0)
        self.assertLessEqual(image.height,2400);image.close()

    def test_window_and_complete_image_callbacks_are_blocked_after_input_changes(self):
        for role in ('manager','sales'):
            with application(role) as (app,folder,*_):
                app.add_fixture_row();app.calculate(notify=False);app.order_no.set('陈旧')
                before=list(folder.rglob('*'))
                with patch('quote_files.quote_images.save_quote_images',side_effect=AssertionError('rendered')), patch('quote_app.window_capture.capture_window',side_effect=AssertionError('captured')):
                    self.assertFalse(app.save_quote_image());self.assertFalse(app._capture_current_quote())
                self.assertEqual(list(folder.rglob('*')),before)

    def test_parallel_same_customer_attachments_have_exclusive_unique_directories(self):
        p=payload(1)
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:save_quote_images(folder,p,'sales'),range(2)))
            self.assertNotEqual(results[0].directory,results[1].directory)
            self.assertEqual(len(list(Path(folder).glob('报价_*'))),2)

    def test_failed_later_page_retains_earlier_verified_image_without_complete_manifest(self):
        import quote_files.quote_images as images
        original=images.save_png
        with tempfile.TemporaryDirectory() as folder:
            calls=[]
            def save(path,image,**kwargs):
                calls.append(path)
                if len(calls)==2:raise FileFailure('合成磁盘错误')
                return original(path,image,**kwargs)
            with patch.object(images,'save_png',side_effect=save):
                with self.assertRaises(FileFailure) as caught:save_quote_images(folder,payload(41),'sales')
            self.assertEqual(len(caught.exception.published_paths),1)
            self.assertTrue(Path(caught.exception.published_paths[0]).is_file())
            self.assertFalse(list(Path(folder).rglob('manifest.json')))

    def test_actual_application_image_output_keeps_excel_and_current_amounts(self):
        for role in ('manager','sales'):
            with application(role) as (app,folder,*_):
                path=export_one(app);before=path.read_bytes();totals=app.quote_session.state.result.totals
                result=app.save_quote_image();self.assertTrue(result)
                self.assertEqual(path.read_bytes(),before);self.assertEqual(app.quote_session.state.result.totals,totals)
                self.assertTrue(Path(result.manifest).is_relative_to(folder))

    def test_window_capture_uses_hwnd_without_desktop_bbox_and_reports_old_pillow(self):
        import quote_app.window_capture as capture
        root=Mock();root.state.return_value='normal'
        with patch.object(capture.os,'name','nt'),patch.object(capture,'native_window_id',return_value=1234):
            with patch('PIL.ImageGrab.grab',return_value=Image.new('RGB',(2,2))) as grab:
                image=capture.capture_window(root);image.close();grab.assert_called_once_with(window=1234)
                root.winfo_rootx.assert_not_called()
            with patch('PIL.ImageGrab.grab',side_effect=TypeError('window')):
                with self.assertRaisesRegex(ValueError,'11.2.1'):capture.capture_window(root)

    def test_minimized_window_capture_refuses_silent_invalid_image(self):
        import quote_app.window_capture as capture
        root=Mock();root.state.return_value='iconic'
        with patch.object(capture.os,'name','nt'),patch('PIL.ImageGrab.grab') as grab:
            with self.assertRaisesRegex(ValueError,'还原'):capture.capture_window(root)
            grab.assert_not_called()

    def test_background_quote_image_uses_frozen_request_after_later_edits(self):
        from threading import Event
        import quote_files.quote_images as images
        with application('manager') as (app,folder,*_):
            ledger=export_one(app);before=ledger.read_bytes()
            revision=app.quote_session.state.revision;expected=app.quote_session.state.result.totals.display()['income']
            with asynchronous(app):
                started,release=Event(),Event();original=images.quote_layout
                def slow(*args,**kwargs):started.set();release.wait(3);return original(*args,**kwargs)
                try:
                    with patch.object(images,'quote_layout',side_effect=slow):
                        task=app.save_quote_image();self.assertTrue(started.wait(1))
                        app.user_name.set('后来的草稿');release.set()
                        wait_for(lambda:task.number not in app._io_callbacks,app._poll_io)
                    report=json.loads(Path(app.last_file_transaction.path).read_text())
                    self.assertEqual(report['draft_revision'],revision);self.assertEqual(report['totals']['销售额'],expected)
                    self.assertEqual(ledger.read_bytes(),before)
                    self.assertIsNone(app.quote_session.state.result)
                finally:release.set()

    def test_window_filename_limits_long_chinese_identity_and_reserves_prefix(self):
        from quote_files.images import unique_window_path
        details=DraftDetails('中文'*100,'CON:/.*测试'*20,'')
        path=unique_window_path(Path('folder'),details)
        self.assertLessEqual(len(path.name),80)
        self.assertTrue(path.name.startswith('窗口_'));self.assertNotIn('/',path.name)

    def test_capture_reentry_that_recalculates_a_new_valid_quote_cannot_save_old_image(self):
        for background in (False,True):
            with application('manager') as (app,folder,*_):
                export_one(app)
                def capture(root):
                    app.quote_session.set_details(DraftDetails('新客户','新订单',''))
                    app.quote_session.calculate()
                    self.assertTrue(app.quote_session.prepare_output('screenshot').allowed)
                    return Image.new('RGB',(2,2))
                with patch('quote_app.window_capture.capture_window',side_effect=capture):
                    if background:
                        with asynchronous(app):self.assertFalse(app._capture_current_quote())
                    else:self.assertFalse(app._capture_current_quote())
                self.assertFalse(list(folder.rglob('*.png')))


if __name__=='__main__':unittest.main()
