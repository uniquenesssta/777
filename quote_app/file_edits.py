"""Owner-thread workbook editing using a captured view, stable IDs and CAS."""
from pathlib import Path
from tkinter import messagebox

from quote_files.transactions import FileFailure, digest, read_bytes, query_request
from quote_files.workbooks import (inspect_receipt, open_book, request, target_order,
                                   view_identity, workbook_transaction)
from quote_files.reading import analyze_raw


class FileEditingMixin:


    def read_excel_view(self, path, sheet_name):
        self._excel_view_hash = None
        self._excel_view_orders = {}
        self._excel_view_path = None
        raw = read_bytes(path)
        book = open_book(raw, for_write=False)
        try:
            result = analyze_raw(raw)
            self._remember_ledger(book, result)
            self._excel_view_orders = view_identity(book, sheet_name) if result.status == "ok" and result.schema.writable else {}
            self.set_feedback(self._read_status(result), is_error=result.status != "ok")
        except Exception:
            book.close()
            raise
        self._excel_view_hash = digest(raw)
        self._excel_view_path = str(Path(path).absolute())
        return book

    def check_last_write(self):
        if self._blocking_file_request:
            blocked = self._blocking_file_request
            try:
                state = query_request(blocked["path"], blocked["request_id"],
                    (lambda *_: None) if Path(blocked["path"]).suffix.lower() in {".json", ".png"} else inspect_receipt)
            except Exception as exc:
                self.set_feedback(f"暂无法核查请求{blocked['request_id']}：{exc}", is_error=True)
                return None
            if state["status"] in {"committed", "not_committed"}:
                self._blocking_file_request = None
                for waiting in (self._excel_pending, self._edit_pending):
                    if waiting and waiting["path"] == blocked["path"]:
                        waiting["unknown"] = False  # This request never ran.
            self.set_feedback(f"待核查请求{blocked['request_id']}：{state['status']}；当前新请求尚未提交。")
            return state
        pending = self._edit_pending if self._edit_pending and self._edit_pending["unknown"] else self._excel_pending
        if pending is None and self._settings_pending is not None:
            pending = self._settings_pending
        if pending is None and self._config_pending is not None:
            pending = {"path": self._price_path(), "request": self._config_pending, "unknown": True}
        if not pending:
            self.set_feedback("本会话暂无Excel写入请求。")
            return None
        req = pending["request"]
        try:
            inspect = (lambda raw, rid: {"fingerprint": req.fingerprint} if digest(raw) == req.fingerprint else None) if req.operation == "config_save" else inspect_receipt
            state = query_request(pending["path"], req.request_id, inspect)
        except Exception as exc:
            self.set_feedback(f"暂无法核查请求{req.request_id}：{exc}", is_error=True)
            return None
        if state["status"] in {"committed", "not_committed"}:
            pending["unknown"] = False
        self.set_feedback(f"请求{req.request_id}：" + {"committed": "已保存，可核对原单。",
            "not_committed": "核查为未提交，可以使用同一请求重试。",
            "not_found": "未找到回执，保持结果不明。", "unknown": "结果不明，先保留恢复副本。"}[state["status"]])
        return state

    def _edit_target(self):
        if self.quote_role != "manager":
            raise FileFailure("子版当前不开放作废/备注编辑")
        path = self.current_excel_path
        row = self.get_selected_excel_row_index()
        identity = self._excel_view_orders.get(row)
        if (not path or str(Path(path).absolute()) != self._excel_view_path
                or self.excel_sheet_var.get() != "利润明细" or not identity or not identity[0]):
            raise FileFailure("请选中带稳定编号的新订单；旧记录保持只读")
        return path, identity[0], identity[1], self._excel_view_hash

    def _finish_file_edit(self, committed):
        self.last_file_transaction = committed
        try:
            self.load_current_excel_sheet()
            self.refresh_excel_files()
        except Exception as exc:
            self.set_feedback(f"请求{committed.request_id}已保存，刷新失败：{exc}。请刷新，勿重复提交。", is_error=True)
        else:
            self.set_feedback(f"请求{committed.request_id}已保存。")

    def _edit_order(self, operation, remark=None):
        if self._blocking_file_request:
            raise FileFailure("存在待核查的旧请求，请先检查上次写入")
        path, order_id, version, expected_hash = self._edit_target()
        key = (path, operation, order_id, version, remark)
        if self._edit_pending and self._edit_pending["unknown"] and self._edit_pending["key"] != key:
            raise FileFailure("上次编辑结果不明，请先检查上次写入")
        if self._edit_pending is None or self._edit_pending["key"] != key:
            req = request(operation, {"order_id": order_id, "order_revision": version, "remark": remark}, order_id=order_id)
            self._edit_pending = {"key": key, "path": path, "request": req, "unknown": False}
        req = self._edit_pending["request"]
        def mutate(book, ws, headers):
            rows = target_order(ws, headers, order_id, version)
            if any(ws.cell(row, headers["记录状态"]).value != "active" for row in rows):
                raise FileFailure("订单已作废；请保留记录，恢复入口尚未开放")
            if operation == "void_order":
                for row in rows:
                    ws.cell(row, headers["记录状态"], "void")
            else:
                totals = [row for row in rows if ws.cell(row, headers["行类型"]).value == "order_total"]
                if len(totals) != 1:
                    raise FileFailure("订单总计身份不完整，未写入")
                notes = book["订单备注"] if "订单备注" in book.sheetnames else book.create_sheet("订单备注")
                if notes.cell(1, 1).value is None:
                    for col, text in enumerate(("请求ID", "订单ID", "备注"), 1):
                        notes.cell(1, col, text)
                elif tuple(c.value for c in notes[1]) != ("请求ID", "订单ID", "备注"):
                    raise FileFailure("备注表格式不支持，未写入")
                notes.append([req.request_id, order_id, remark])
                notes.cell(notes.max_row, 3).data_type = "s"
                if "备注" not in headers:
                    headers["备注"] = ws.max_column + 1
                    ws.cell(self.find_excel_table_header(ws)[0], headers["备注"], "备注")
                cell = ws.cell(totals[0], headers["备注"])
                cell.value = (str(cell.value) + "\n" if cell.value else "") + remark
                cell.data_type = "s"
            for row in rows:
                ws.cell(row, headers["订单版本"], version + 1)
            self.recompute_daily_profit_summary(ws)
            return {"order_revision": version + 1}
        def no_create():
            raise FileFailure("当前文件不存在，未创建替代文件")
        from quote_files.transactions import UnknownCommit
        try:
            committed = workbook_transaction(path, req, self.get_excel_headers(), no_create, mutate,
                                             expected_hash=expected_hash, check_hash=True)
        except UnknownCommit as exc:
            self._edit_pending["unknown"] = True
            if exc.request_id and exc.request_id != req.request_id:
                self._blocking_file_request = {"path": str(path), "request_id": exc.request_id}
            raise
        self._finish_file_edit(committed)
        return committed

    def delete_current_excel_row(self):
        try:
            path, order_id, version, _ = self._edit_target()
            if not messagebox.askyesno("作废选中订单", f"将作废选中订单（版本{version}），保留金额和原记录供恢复。\n文件：{Path(path).name}"):
                return False
            return self._edit_order("void_order")
        except Exception as exc:
            self.set_feedback(f"作废未确认：{exc}" + (f"；请求{exc.request_id}，请检查上次写入。" if getattr(exc, "request_id", None) else ""), is_error=True)
            return False

    def save_current_excel_remark(self):
        try:
            remark = self.excel_remark_text.get("1.0", "end").strip()
            if not remark or len(remark) > 4096:
                raise FileFailure("请输入1至4096字符的追加备注")
            result = self._edit_order("append_remark", remark)
            self.excel_remark_text.delete("1.0", "end")
            return result
        except Exception as exc:
            self.set_feedback(f"备注未确认：{exc}" + (f"；请求{exc.request_id}，请检查上次写入。" if getattr(exc, "request_id", None) else ""), is_error=True)
            return False

    def load_current_excel_remark(self):
        # This is an append editor, not an editable copy of the entire history.
        if hasattr(self, "excel_remark_text"):
            self.excel_remark_text.delete("1.0", "end")

    def delete_excel_path(self, path):
        self.set_feedback("整文件删除已停用；请按订单作废，保留原记录。", is_error=True)
        return False
