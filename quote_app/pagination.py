"""Bounded owner-thread presentation of complete, worker-built workbook views."""
from collections import OrderedDict
from pathlib import Path

from quote_files.scheduling import checkpoint

PAGE_SIZE = 200


def insert_page_items(tree, items):
    """One bounded Tcl call; cell contents are list data, never Tcl source."""
    if hasattr(tree, 'tk') and hasattr(tree, '_w'):
        words = tuple(word for item in items for word in item)
        tree.tk.call('apply', (('widget', 'rows'),
            'foreach {iid values} $rows {$widget insert {} end -id $iid -values $values}'), tree._w, words)
    else:
        for iid, values in items:tree.insert('', 'end', iid=iid, values=values)


def filter_view(view, query='', group=None, context=None):
    """Indices address original worksheet rows; amounts and edit identities stay intact."""
    needle = query.strip().casefold()
    matches = []
    for index, (row, values) in enumerate(view.rows):
        checkpoint()
        if context is not None:
            context.check()
        if group is not None and view.ledger.group_keys.get(row) != group:
            continue
        if needle and not any(needle in str(value).casefold() for value in values):
            continue
        matches.append(index)
    return tuple(matches)


class PaginationMixin:
    def install_excel_pagination(self, parent):
        from tkinter import ttk
        bar = ttk.Frame(parent)
        bar.pack(fill='x', pady=(0, 6))
        self.excel_filter_var = self._new_text_var('')
        self.excel_page_var = self._new_text_var('1')
        self.excel_page_status = self._new_text_var('尚未读取；每页200行')
        ttk.Label(bar, text='筛选：').pack(side='left')
        entry = ttk.Entry(bar, textvariable=self.excel_filter_var, width=24)
        entry.pack(side='left', padx=4)
        entry.bind('<Return>', lambda _: self.filter_excel_view())
        self.excel_filter_button = ttk.Button(bar, text='搜索', command=self.filter_excel_view)
        self.excel_filter_button.pack(side='left')
        ttk.Button(bar, text='仅选中订单', command=self.filter_selected_excel_order).pack(side='left', padx=4)
        ttk.Button(bar, text='清除筛选', command=self.clear_excel_filter).pack(side='left')
        self.excel_prev_button = ttk.Button(bar, text='上一页', command=lambda: self.change_excel_page(-1), state='disabled')
        self.excel_prev_button.pack(side='left', padx=(12, 4))
        self.excel_next_button = ttk.Button(bar, text='下一页', command=lambda: self.change_excel_page(1), state='disabled')
        self.excel_next_button.pack(side='left')
        ttk.Entry(bar, textvariable=self.excel_page_var, width=5).pack(side='left', padx=4)
        self.excel_jump_button = ttk.Button(bar, text='跳转', command=self.jump_excel_page)
        self.excel_jump_button.pack(side='left')
        ttk.Label(parent, textvariable=self.excel_page_status).pack(anchor='w', pady=(0, 4))

    def _remember_page_location(self):
        view = getattr(self, '_page_view', None)
        if view is None:
            return
        if not hasattr(self, '_page_locations'):
            self._page_locations = OrderedDict()
        tree = self.excel_view_tree
        selected = self.get_selected_excel_row_index()
        previous = getattr(self, '_page_selected', None)
        if selected is not None:
            self._page_selected = selected
        location = {'page': self._page_number, 'query': self._page_query, 'group': self._page_group,
                    'selected': selected if selected is not None else previous,
                    'order_id': view.identities.get(selected if selected is not None else previous, (None,))[0],
                    'y': tree.yview()[0] if hasattr(tree, 'yview') else 0,
                    'x': tree.xview()[0] if hasattr(tree, 'xview') else 0}
        key = (view.path, view.sheet)
        self._page_locations[key] = location
        self._page_locations.move_to_end(key)
        while len(self._page_locations) > 64:
            self._page_locations.popitem(last=False)
        return location

    def reset_excel_pagination(self):
        self._page_view = None
        self._page_locations = OrderedDict()
        self._page_selected = None
        if hasattr(self, 'excel_page_status'):
            self.excel_page_status.set('目录已切换，请重新选择文件。')

    def _open_paged_sync(self, path, sheet=None):
        from quote_files.views import read_view
        class Context:
            def check(self):pass
        self._remember_page_location()
        try:
            self._set_paged_view(read_view(path, sheet, self.quote_role, Context()), object())
            return True
        except Exception as exc:
            self._excel_view_hash = self._excel_view_path = None
            self._excel_view_orders = {};self._excel_order_views = {}
            self.set_feedback('读取失败：' + str(exc), is_error=True)
            return False

    def _set_paged_view(self, view, token):
        self._remember_page_location()
        locations = getattr(self, '_page_locations', {})
        old = locations.get((view.path, view.sheet), {})
        self._page_view = view
        self._page_selected = old.get('selected')
        self._page_query, self._page_group = old.get('query', ''), old.get('group')
        self._page_number = old.get('page', 0)
        # Queries are normally built by the worker; saved locations need the
        # same asynchronous filtering path before restoring a bounded page.
        self._page_indices = () if self._page_query or self._page_group is not None else tuple(range(len(view.rows)))
        self.current_excel_path = view.path
        self.excel_selected_file.set(view.path)
        self.excel_sheet_combo.configure(values=view.sheets)
        self.excel_sheet_var.set(view.sheet)
        if hasattr(self, 'excel_filter_var'):
            self.excel_filter_var.set(self._page_query)
        self._excel_view_orders = view.identities
        self._excel_order_views = view.orders
        self._excel_view_hash = view.ledger.source_sha256
        self._excel_view_path = view.path
        self._io_last_view = view if view.ledger.status == 'ok' else None
        self.show_excel_detail()
        if old.get('order_id') and view.identities.get(old.get('selected'), (None,))[0] != old['order_id']:
            index = next((i for i,(row,_) in enumerate(view.rows) if view.identities.get(row,(None,))[0] == old['order_id']), None)
            self._page_selected = view.rows[index][0] if index is not None else None
            old = {**old,'selected':self._page_selected,'page':index//PAGE_SIZE if index is not None else 0}
            self._page_number = old['page']
        self._render_page(restore=old)
        if self._page_query or self._page_group is not None:
            self._filter_paged(self._page_query, self._page_group, restore=old)
        order_id = getattr(self, '_io_reselect', None)
        if order_id:
            selected = self.get_selected_excel_row_index()
            if self._excel_view_orders.get(selected,(None,))[0] != order_id:
                self.select_excel_order(order_id)
            self._io_reselect = None
        self.set_feedback(self._read_status(view.ledger), is_error=view.ledger.status != 'ok')

    def _render_page(self, restore=None):
        view = self._page_view
        count = len(self._page_indices)
        pages = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
        self._page_number = min(max(0, self._page_number), pages - 1)
        tree = self.excel_view_tree
        # Save the original order's draft before changing the visible row map.
        if self.quote_role == 'manager' and hasattr(self, 'excel_remark_text'):
            self.load_current_excel_remark()
        tree.delete(*tree.get_children())
        columns = tuple(f'c{i}' for i in range(len(view.headings)))
        if getattr(self, '_page_heading_state', None) != (tree, view.headings):
            tree.configure(columns=columns, show='headings')
            for column, heading in zip(columns, view.headings):
                tree.heading(column, text=heading)
                tree.column(column, width=140, anchor='w')
            self._page_heading_state = (tree, view.headings)
        self.excel_view_row_map = {}
        begin = self._page_number * PAGE_SIZE
        items = []
        for index in self._page_indices[begin:begin + PAGE_SIZE]:
            row, values = view.rows[index]
            item = f'row_{row}'
            items.append((item, values))
            self.excel_view_row_map[item] = row
        insert_page_items(tree, items)
        row = (restore or {}).get('selected', self._page_selected)
        if row is not None and f'row_{row}' in self.excel_view_row_map:
            tree.selection_set(f'row_{row}')
            tree.see(f'row_{row}')
        elif hasattr(tree, 'selection_remove'):
            tree.selection_remove(*tree.selection())
        if restore:
            if hasattr(tree, 'yview_moveto'):tree.yview_moveto(restore.get('y', 0))
            if hasattr(tree, 'xview_moveto'):tree.xview_moveto(restore.get('x', 0))
        if hasattr(self, 'excel_page_status'):
            shown = min(PAGE_SIZE, max(0, count - begin))
            detail = view.ledger.detail_count if view.ledger.status == 'ok' and view.sheet == '利润明细' else '—'
            self.excel_page_status.set(f'第{self._page_number + 1}/{pages}页 ｜ 本页{shown}行 ｜ 筛选{count}/{len(view.rows)}行 ｜ 文件明细{detail}行' +
                                       (' ｜ 仅选中订单' if self._page_group is not None else ''))
            self.excel_page_var.set(str(self._page_number + 1))
            self.excel_prev_button.configure(state='normal' if self._page_number else 'disabled')
            self.excel_next_button.configure(state='normal' if self._page_number + 1 < pages else 'disabled')
        if self.quote_role == 'manager':
            self.load_current_excel_remark()

    def change_excel_page(self, delta):
        if getattr(self, '_page_view', None) is None:return False
        self._remember_page_location()
        self._page_number += delta
        self._render_page()
        return True

    def jump_excel_page(self):
        try:
            number = int(self.excel_page_var.get())
            pages = max(1, (len(self._page_indices) + PAGE_SIZE - 1) // PAGE_SIZE)
            if not 1 <= number <= pages:raise ValueError()
        except (ValueError, TypeError):
            self.set_feedback('请输入范围内的页码。', is_error=True)
            return False
        self._remember_page_location();self._page_number = number - 1;self._render_page()
        return True

    def _filter_paged(self, query, group=None, restore=None):
        view = getattr(self, '_page_view', None)
        if view is None:return False
        if len(query) > 256:
            self.set_feedback('筛选词最多256字符。', is_error=True);return False
        self._remember_page_location()
        def apply(indices, *_):
            if self._page_view is not view:return
            self._page_query, self._page_group = query, group
            self._page_indices = indices
            self._page_number = restore.get('page', 0) if restore else 0
            self._render_page(restore=restore)
        if self._io_enabled():
            return self._submit_io('page_filter', 'view', apply, arguments=(view, query, group))
        apply(filter_view(view, query, group));return True

    def filter_excel_view(self):
        return self._filter_paged(self.excel_filter_var.get().strip())

    def filter_selected_excel_order(self):
        view = getattr(self, '_page_view', None)
        row = self.get_selected_excel_row_index()
        group = view.ledger.group_keys.get(row) if view else None
        if group is None or group[0] == 'unresolved':
            self.set_feedback('请选择可识别归属的订单明细；历史歧义不能推断成同一订单。', is_error=True)
            return False
        if hasattr(self, 'excel_filter_var'):self.excel_filter_var.set('')
        return self._filter_paged('', group)

    def clear_excel_filter(self):
        if hasattr(self, 'excel_filter_var'):self.excel_filter_var.set('')
        return self._filter_paged('')

    def select_excel_order(self, order_id):
        view = getattr(self, '_page_view', None)
        if view is not None:
            indices = self._page_indices
            match = next((position for position, index in enumerate(indices)
                          if view.identities.get(view.rows[index][0], (None,))[0] == order_id), None)
            if match is not None:
                self._page_number = match // PAGE_SIZE
                self._page_selected = view.rows[indices[match]][0]
                self._render_page()
        return super().select_excel_order(order_id)
