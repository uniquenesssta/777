"""Owner-thread workbook editing using a captured view, stable IDs and CAS."""
from pathlib import Path
from tkinter import messagebox

from quote_files.transactions import FileFailure, digest, read_bytes, query_request
from quote_files.workbooks import (inspect_receipt, open_book, request,
                                   view_identity, workbook_transaction)
from quote_files.reading import analyze_raw
from quote_files.orders import edit_order, order_views


class FileEditingMixin:


    def read_excel_view(self, path, sheet_name):
        self._excel_view_hash = None
        self._excel_view_orders = {}
        self._excel_view_path = None
        self._excel_order_views = {}
        raw = read_bytes(path)
        book = open_book(raw, for_write=False)
        try:
            result = analyze_raw(raw)
            self._remember_ledger(book, result)
            self._excel_view_orders = view_identity(book, sheet_name) if result.status == "ok" and result.schema.writable else {}
            if result.status == "ok" and result.schema.identified:
                self._excel_order_views = order_views(book, result.schema)
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
        if state["status"] == "committed" and pending is self._edit_pending:
            from quote_files.transactions import CommitResult
            committed = CommitResult(pending["path"], req.request_id, state["result"], True, state["content_sha256"])
            self._finish_file_edit(committed)
            return state
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
            if self.load_current_excel_sheet() is False:
                raise FileFailure("当前工作表未能重新读取")
            self.refresh_excel_files()
            self.select_excel_order(committed.result["order_id"])
        except Exception as exc:
            self.set_feedback(f"请求{committed.request_id}已保存，刷新失败：{exc}。请刷新，勿重复提交。", is_error=True)
        else:
            self.set_feedback(f"请求{committed.request_id}已保存。")

    def _edit_order(self, operation, remark=None, *, reason=None, target=None):
        if operation not in {"append_remark", "void_order", "restore_order"}:
            raise FileFailure("未知订单操作，未写入")
        if self._blocking_file_request:
            raise FileFailure("存在待核查的旧请求，请先检查上次写入")
        current = self._edit_target()
        if target is not None and current != target:
            raise FileFailure("确认期间选中订单或读取版本已变化；请重新选择并确认")
        path, order_id, version, expected_hash = target or current
        content = remark if operation == "append_remark" else reason
        if type(content) is not str or not content.strip() or len(content.strip()) > 4096:
            raise FileFailure("请输入1至4096字符的" + ("追加备注" if operation == "append_remark" else "操作原因"))
        content = content.strip()
        key = (path, operation, order_id, version, content)
        if self._edit_pending and self._edit_pending["unknown"] and self._edit_pending["key"] != key:
            raise FileFailure("上次编辑结果不明，请先检查上次写入")
        if self._edit_pending is None or self._edit_pending["key"] != key:
            req = request(operation, {"order_id": order_id, "order_revision": version, "content": content}, order_id=order_id)
            self._edit_pending = {"key": key, "path": path, "request": req, "unknown": False}
        req = self._edit_pending["request"]
        def mutate(book, ws, headers):
            detail = edit_order(book, ws, headers, req, version, text=content if operation == "append_remark" else None,
                                reason=content if operation != "append_remark" else None)
            self.recompute_daily_profit_summary(ws)
            return detail
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
        return self._confirm_order_state("void_order")

    def restore_current_excel_order(self):
        return self._confirm_order_state("restore_order")

    def _confirm_order_state(self, operation):
        label = "作废" if operation == "void_order" else "恢复"
        try:
            target = self._edit_target()
            path, order_id, version, _ = target
            view = self._excel_order_views.get(order_id)
            required = "active" if operation == "void_order" else "void"
            if not view or view.state != required:
                raise FileFailure("请选择" + ("有效" if required == "active" else "作废") + "订单")
            reason = self.excel_order_reason.get().strip()
            if not reason or len(reason) > 4096:
                raise FileFailure("请先填写1至4096字符的操作原因")
            effect = "原记录和历史保留，金额移出有效汇总" if operation == "void_order" else "原订单恢复有效，金额重新计入汇总一次"
            if not messagebox.askyesno(label + "选中订单", f"订单：{order_id}\n版本：{version}\n文件：{Path(path).name}\n原因：{reason}\n{effect}。\n确认{label}？"):
                self.set_feedback(f"已取消{label}，文件未改动。")
                return False
            result = self._edit_order(operation, reason=reason, target=target)
            self.excel_order_reason.set("")
            return result
        except Exception as exc:
            self.set_feedback(f"{label}未确认：{exc}" + (f"；请求{exc.request_id}，请检查上次写入。" if getattr(exc, "request_id", None) else ""), is_error=True)
            return False

    def save_current_excel_remark(self):
        try:
            remark = self.excel_remark_text.get("1.0", "end").strip()
            if not remark or len(remark) > 4096:
                raise FileFailure("请输入1至4096字符的追加备注")
            result = self._edit_order("append_remark", remark)
            self.excel_remark_text.delete("1.0", "end")
            if self._remark_editor_order:
                self._remark_drafts.pop(self._remark_editor_order, None)
            return result
        except Exception as exc:
            self.set_feedback(f"备注未确认：{exc}" + (f"；请求{exc.request_id}，请检查上次写入。" if getattr(exc, "request_id", None) else ""), is_error=True)
            return False

    def load_current_excel_remark(self):
        row = self.get_selected_excel_row_index()
        identity = self._excel_view_orders.get(row)
        valid_path = bool(self.current_excel_path and str(Path(self.current_excel_path).absolute()) == self._excel_view_path)
        view = self._excel_order_views.get(identity[0]) if identity and valid_path and self.excel_sheet_var.get() == "利润明细" else None
        key = (self._excel_view_path, view.order_id) if view else None
        if hasattr(self, "excel_remark_text"):
            if self._remark_editor_order is not None:
                self._remark_drafts[self._remark_editor_order] = self.excel_remark_text.get("1.0", "end").strip()
            self.excel_remark_text.configure(state="normal")
            self.excel_remark_text.delete("1.0", "end")
            self.excel_remark_text.insert("1.0", self._remark_drafts.get(key, ""))
            self.excel_remark_text.configure(state="normal" if view and view.state == "active" else "disabled")
        self._remark_editor_order = key
        label = "请选择利润明细中带稳定编号的新订单；旧记录只读。"
        history = ""
        if view:
            label = f"订单 {view.order_id} ｜ 版本 {view.revision} ｜ " + ("有效" if view.state == "active" else "已作废，不计有效汇总；历史仍保留")
            lines = ["备注历史（更正请追加，原备注保留）："]
            lines.extend(f"{n + 1}. {text}" for n, (_, text) in enumerate(view.notes))
            if not view.notes:
                lines.append("暂无追加备注。")
            if view.legacy_remark:
                lines.append("旧版订单总计备注（缺少追加回执来源）：\n" + view.legacy_remark)
            lines.append("\n操作记录：")
            names = {"append_quote": "新增订单", "append_remark": "追加备注", "void_order": "作废", "restore_order": "恢复"}
            for rid, op, timestamp, revision, reason in view.events:
                lines.append(f"{timestamp} ｜ {names[op]} ｜ 版本{revision} ｜ 请求{rid}" +
                             (f"\n原因：{reason or '旧回执未登记原因'}" if op in {"void_order", "restore_order"} else ""))
            lines.append(f"\n关联输入检查 {len(view.inputs)} 条；价格快照 {len(view.prices)} 条，均保留原文。")
            history = "\n".join(lines)
        if hasattr(self, "excel_order_label"):
            self.excel_order_label.set(label)
        if hasattr(self, "excel_order_history"):
            self.excel_order_history.configure(state="normal")
            self.excel_order_history.delete("1.0", "end")
            self.excel_order_history.insert("1.0", history)
            self.excel_order_history.configure(state="disabled")
        for name, state in (("excel_void_button", "active"), ("excel_restore_button", "void"), ("excel_note_button", "active")):
            if hasattr(self, name):
                getattr(self, name).configure(state="normal" if view and view.state == state else "disabled")
        return view

    def select_excel_order(self, order_id):
        if not hasattr(self, "excel_view_tree"):
            return
        for item, row in self.excel_view_row_map.items():
            identity = self._excel_view_orders.get(row)
            if identity and identity[0] == order_id:
                self.excel_view_tree.selection_set(item)
                self.excel_view_tree.see(item)
                break
        self.load_current_excel_remark()

    def delete_excel_path(self, path):
        self.set_feedback("整文件删除已停用；请按订单作废，保留原记录。", is_error=True)
        return False
