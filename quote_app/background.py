"""Owner-thread snapshots and delivery; I/O controllers contain no Tk objects."""
from copy import copy, deepcopy
from pathlib import Path
import threading
import time

from .jobs import Jobs, QueueFull

FIELDS = ("quote_session", "quote_role", "local_settings_file", "legacy_data_root", "default_items",
    "data_root", "config_file", "report_dir", "image_dir", "default_report_dir", "active_price_config",
    "price_changes", "_config_load_problem", "_storage_version", "_local_hash", "_shared_hash",
    "_local_bad", "_shared_bad", "_storage_valid", "_last_config_sha", "_settings_pending", "_config_pending",
    "_excel_pending", "_edit_pending", "_blocking_file_request", "last_file_transaction", "current_excel_path",
    "_excel_view_hash", "_excel_view_path", "_excel_view_orders", "_excel_order_views", "last_config_snapshot")
VARS = ("data_source_var", "backup_dir_var", "price_file_var", "screenshot_dir_var", "config_source_var",
        "storage_status_var", "export_dir_var", "user_name", "order_no", "wechat_no")
STORAGE = ("data_root", "config_file", "report_dir", "image_dir", "_local_hash", "_shared_hash", "_local_bad",
           "_shared_bad", "_storage_valid", "_storage_version", "_last_config_sha")
PENDING = ("_settings_pending", "_config_pending", "_excel_pending", "_edit_pending", "_blocking_file_request", "last_file_transaction")


class Value:
    def __init__(self, value):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


def capture(app):
    app._assert_io_owner()
    state = {name: clone_value(name, getattr(app, name)) for name in FIELDS if hasattr(app, name)}
    state["variables"] = {name: getattr(app, name).get() for name in VARS if hasattr(app, name)}
    state["setting_rows"] = [{name: row[name].get() for name in ("name", "sale", "cost", "k", "single")} for row in app.setting_rows]
    state["selected_row"] = app.get_selected_excel_row_index() if hasattr(app, "excel_view_tree") else None
    state["sheet"] = app.excel_sheet_var.get() if hasattr(app, "excel_sheet_var") else ""
    return state


def clone_value(name, value):
    # Session state is immutable dataclasses/tuples; its methods replace fields.
    # Order projections are read-only here and never mutated by the worker.
    return copy(value) if name in {"quote_session", "_excel_view_orders", "_excel_order_views"} else deepcopy(value)


def controller(parent, snapshot, context):
    # Only pure entrypoint helpers (format/style/path) are inherited. UI methods
    # used by the existing transaction controller are replaced explicitly.
    class Worker(parent):
        def _new_text_var(self, text):
            return Value(text)
        def set_feedback(self, text, is_error=False):
            self.feedback = (text, is_error)
        def clear_quote_display(self):
            pass
        def update_quote_status(self):
            pass
        def render_issues(self, *_):
            pass
        def refresh_item_selector(self):
            pass
        def update_calc_row_states(self, *_):
            pass
        def refresh_excel_files(self):
            pass
        def quote_input_changed(self, *_):
            self.quote_session.invalidate_inputs()
        def _replace_setting_rows(self, prices):
            self.setting_rows = [{"name": Value(p.product_id), "sale": Value(p.sale), "cost": Value(p.cost),
                "k": Value(p.k), "single": Value(p.single), "frame": None} for p in prices.items]
        def get_selected_excel_row_index(self):
            return snapshot["selected_row"]
        def _finish_file_edit(self, committed):
            self.last_file_transaction = committed
            self.set_feedback(f"请求{committed.request_id}已保存。")
        def _report_io_request(self, kind, path, req):
            context.progress({"kind": kind, "path": str(path), "request": req})
        def _write_quote_screenshot(self, payload):
            from quote_files.images import save_png
            folder = self.get_daily_screenshot_dir() if self.quote_role == "sales" else self.image_dir
            Path(folder).mkdir(parents=True, exist_ok=True)
            from uuid import uuid4
            name = self.clean_filename(payload.details.customer)[:60]
            order = self.clean_filename(payload.details.order_ref)[:60] or "未填订单号"
            path = Path(folder) / f"{name}_{order}_{time.time_ns()}_{uuid4().hex}.png"
            try:
                self.last_file_transaction = save_png(path, self.captured_image,
                    on_request=lambda rid: context.progress({"kind": "screenshot", "path": str(path), "request_id": rid}))
            except Exception as exc:
                if getattr(exc, "request_id", None):
                    self._blocking_file_request = {"path": str(path), "request_id": exc.request_id}
                raise
            return str(path)
    worker = Worker.__new__(Worker)
    worker._io_runtime = None
    worker._loading_prices = False
    worker.feedback = ("", False)
    worker.calc_rows = []
    for name in FIELDS:
        if name in snapshot:
            setattr(worker, name, clone_value(name, snapshot[name]))
    for name, value in snapshot["variables"].items():
        setattr(worker, name, Value(value))
    worker.excel_sheet_var = Value(snapshot["sheet"])
    worker.setting_rows = [{**{k: Value(v) for k, v in row.items()}, "frame": None} for row in snapshot["setting_rows"]]
    return worker


def perform(worker, operation, arguments, context):
    context.check()
    if operation == "startup":
        worker._restore_connection()
        value = worker.reload_price_settings_from_json(first_load=True, silent=True)
    elif operation == "observe":
        value = worker._observe_price_file()
    elif operation == "scan":
        import os
        from quote_files.reading import read_ledger
        if not worker.observe_storage():
            raise OSError(worker.storage_status_var.get())
        results = {}
        stamps = {}
        paths = [os.path.join(worker.report_dir, name) for name in os.listdir(worker.report_dir)
                 if not name.startswith("~$") and name.lower().endswith(".xlsx")]
        for path in paths:
            context.check()
            result = read_ledger(path)
            try:
                stamps[path] = os.path.getmtime(path)
                modified = time.strftime("%Y-%m-%d %H:%M", time.localtime(stamps[path]))
            except OSError:
                stamps[path] = -1
                modified = "无法获取"
            results[path] = (result, modified)
        value = dict(sorted(results.items(), key=lambda pair: stamps[pair[0]], reverse=True))
    elif operation == "view":
        from quote_files.views import read_view
        value = read_view(arguments[0], arguments[1], worker.quote_role, context)
    elif operation == "excel":
        value = worker._formal_output("excel", worker._write_quote_excel)
    elif operation == "screenshot":
        worker.captured_image = arguments[0]
        value = worker._formal_output("screenshot", worker._write_quote_screenshot)
    elif operation == "edit":
        value = worker._edit_order(*arguments[0], **arguments[1])
    elif operation == "confirm":
        worker._observe_price_file()
        value = worker.quote_session.confirm_prices(expected_revision=arguments[0])
    else:
        value = getattr(worker, operation)(**arguments)
    context.check()
    return value


def run(parent, snapshot, operation, arguments, context):
    worker = controller(parent, snapshot, context)
    error = None
    try:
        value = perform(worker, operation, arguments, context)
    except Exception as exc:
        error, value = exc, False
    return {"value": value, "error": error, "fields": {name: getattr(worker, name) for name in FIELDS if hasattr(worker, name)},
            "variables": {name: getattr(worker, name).get() for name in VARS if hasattr(worker, name)},
            "feedback": worker.feedback}


class BackgroundApplicationMixin:
    background_io_enabled = True
    io_timeout = 30

    def initialize_background_io(self):
        self._io_owner = threading.get_ident()
        self._io_runtime = Jobs(timeout=self.io_timeout) if self.background_io_enabled else None
        self._io_callbacks, self._io_epoch = {}, 0
        self._io_closing = False
        self._io_starting = False
        self._io_render_task = None
        self.background_status_var = self._new_text_var("后台I/O就绪")
        if self._io_runtime:
            self._io_poll_job = self.root.after(40, self._poll_io)

    def _assert_io_owner(self):
        if threading.get_ident() != self._io_owner:
            raise RuntimeError("仅主线程可以读取或更新界面")

    def _io_enabled(self):
        return getattr(self, "_io_runtime", None) is not None

    def install_background_controls(self):
        if not self._io_enabled():
            return
        from tkinter import ttk
        box = ttk.Frame(self.root, padding=(12, 4))
        box.pack(side="bottom", fill="x")
        ttk.Label(box, textvariable=self.background_status_var, wraplength=900).pack(side="left", fill="x", expand=True)
        ttk.Button(box, text="取消读取", command=self.cancel_background_reads).pack(side="right")

    def _submit_io(self, operation, channel, callback, *, write=False, arguments=None):
        self._assert_io_owner()
        if self._io_closing:
            return False
        # A write freezes the connection until its authoritative result arrives.
        if write and self._io_starting:
            self.set_feedback("数据源仍在读取，请等待后再保存。", is_error=True)
            return False
        if write and (self._blocking_file_request or any(p and p.get("unknown") for p in (self._excel_pending, self._edit_pending, self._settings_pending))):
            self.set_feedback("存在结果不明的写入；请先检查上次写入，保留原请求。", is_error=True)
            return False
        parent, snapshot = type(self), capture(self)
        try:
            task = self._io_runtime.submit(channel,
                lambda context: run(parent, snapshot, operation, arguments, context), write=write)
        except QueueFull as exc:
            self.background_status_var.set(str(exc))
            self.set_feedback(str(exc), is_error=True)
            return False
        self._io_callbacks = {n: data for n, data in self._io_callbacks.items() if n in self._io_runtime.tasks}
        self._io_callbacks[task.number] = (self._io_epoch, self.quote_session.state.revision, operation, callback, snapshot["variables"])
        self.background_status_var.set(f"{'写入' if write else '读取'}任务{task.number}进行中，可以继续编辑。")
        return task

    def _poll_io(self):
        self._assert_io_owner()
        for task, state, data in self._io_runtime.drain():
            delivery = self._io_callbacks.get(task.number)
            if not delivery:
                continue
            epoch, revision, operation, callback, original_vars = delivery
            if state == "progress":
                if task.write:
                    req = data.get("request")
                    rid = req.request_id if req else data.get("request_id")
                    self.background_status_var.set(f"写入任务{task.number}：请求{rid}，结果尚未确认。")
                continue
            if state == "timeout":
                if operation == "startup":
                    self._io_starting = False
                text = ("写入等待超时，提交仍可能进行中；保留原任务，先等待或核查结果。" if task.write else
                        "读取超时，停止更新本次显示；底层I/O仍可能进行中，请检查共享目录。")
                self.background_status_var.set(text)
                self.set_feedback(text, is_error=True)
                continue
            self._io_callbacks.pop(task.number, None)
            if not task.write and (epoch != self._io_epoch or not self._io_runtime.current(task) or self._io_closing):
                continue
            if state == "failed":
                self.set_feedback(f"任务{task.number}未确认：{data}" + (f"；请求{data.request_id}，请检查上次写入。" if getattr(data, "request_id", None) else ""), is_error=True)
                if task.write and getattr(data, "request_id", None):
                    self._blocking_file_request = {"path": getattr(data, "target_path", None) or self.current_excel_path or self.get_daily_excel_path(), "request_id": data.request_id}
                self.background_status_var.set(f"任务{task.number}失败，已保留上次显示。")
            elif state == "completed":
                try:
                    fresh = revision == self.quote_session.state.revision
                    self._apply_io_state(data, revision, operation, task.write, original_vars)
                    if data["error"]:
                        error = data["error"]
                        self.set_feedback(f"任务{task.number}未确认：{error}" +
                            (f"；请求{error.request_id}，请检查上次写入。" if getattr(error, "request_id", None) else ""), is_error=True)
                    else:
                        callback(data["value"], self.quote_session.state.revision if fresh else revision, task)
                except Exception as exc:
                    self.set_feedback(f"任务{task.number}结果已返回，界面更新失败：{exc}；请核查上次写入。", is_error=True)
                if not self._io_closing:
                    pending = len(self._io_runtime.tasks)
                    self.background_status_var.set(f"任务{task.number}" + ("失败，保留上次显示。" if data["error"] else "已结束。") +
                        (f"仍有{pending}项I/O未结束。" if pending else ""))
            if operation == "startup":
                self._io_starting = False
        if self._io_closing and not self._io_runtime.writing:
            self._destroy_after_io()
            return
        self._io_poll_job = self.root.after(40, self._poll_io)

    def _apply_io_state(self, data, revision, operation, write, original_vars):
        fields = data["fields"]
        stale_load = revision != self.quote_session.state.revision and operation in {
            "startup", "reload_price_settings_from_json", "save_settings", "apply_connection"}
        if operation != "view" and (write or not self._io_runtime.writing):
            changed = any(getattr(self, n, None) != fields.get(n) for n in ("data_root", "config_file", "report_dir"))
            for name in STORAGE:
                if name in fields:
                    setattr(self, name, fields[name])
            for name in VARS[:7]:
                if name in data["variables"] and getattr(self, name).get() == original_vars.get(name):
                    getattr(self, name).set(data["variables"][name])
            if changed:
                self._io_epoch += 1
                self._io_runtime.cancel_reads()
                self._excel_view_orders = {}
                self._excel_view_hash = self._excel_view_path = None
                self.current_excel_path = None
                self._io_last_view = None
                self._io_last_files = None
                self._io_files_token = None
                if hasattr(self, "excel_file_tree"):
                    self.excel_file_tree.delete(*self.excel_file_tree.get_children())
                if hasattr(self, "excel_view_tree"):
                    self.excel_view_tree.delete(*self.excel_view_tree.get_children())
                if hasattr(self, "excel_selected_file"):
                    self.excel_selected_file.set("目录已切换，请重新选择文件。")
                    self.excel_sheet_var.set("")
                for name in ("income", "cost", "profit", "margin"):
                    if hasattr(self, "excel_total_" + name):
                        getattr(self, "excel_total_" + name).set("—")
                if hasattr(self, "excel_total_count"):
                    self.excel_total_count.set("待重新统算")
        if write or operation == "check_last_write":
            for name in PENDING:
                setattr(self, name, fields[name])
        if revision == self.quote_session.state.revision and operation not in {"scan", "view"}:
            self.quote_session = fields["quote_session"]
            self._config_load_problem = fields["_config_load_problem"]
            self.price_changes = fields["price_changes"]
            if operation in {"startup", "reload_price_settings_from_json", "save_settings", "apply_connection"}:
                self.active_price_config = fields["active_price_config"]
                if self.active_price_config:
                    self._replace_setting_rows(self.active_price_config.prices)
                    self.last_config_snapshot = fields.get("last_config_snapshot", {})
                    self.refresh_item_selector()
                    self.update_calc_row_states(self.last_config_snapshot)
                self.clear_quote_display()
            self.update_quote_status()
            if self.quote_session.state.result is None:
                self.clear_quote_display()
        elif operation in {"startup", "reload_price_settings_from_json", "save_settings", "apply_connection"}:
            state = fields["quote_session"].state
            self.quote_session.observe_price_source(state.price_source, latest_price_version_id=state.latest_price_version_id)
            self.update_quote_status()
            self.set_feedback("文件读取/保存已完成，编辑已变化；保留当前草稿，请再次刷新并核对。")
        if write or operation not in {"scan", "view"}:
            text, error = data["feedback"]
            if text and not stale_load:
                self.set_feedback(text, is_error=error)
            elif stale_load and error:
                self.set_feedback(text + "；已保留当前草稿。", is_error=True)

    def initialize_connections(self):
        if not self._io_enabled():
            return super().initialize_connections()
        self._initialize_connection_fields()
        self._io_starting = True
        self._submit_io("startup", "source", self._source_loaded)

    def _source_loaded(self, value, revision, task):
        self._io_starting = False
        self.refresh_excel_files()

    def reload_price_settings_from_json(self, silent=False, first_load=False):
        if not self._io_enabled():
            return super().reload_price_settings_from_json(silent=silent, first_load=first_load)
        if self._io_starting:
            return False
        if not self.data_root:
            self._io_starting = True
            return self._submit_io("startup", "source", self._source_loaded)
        return self._submit_io("reload_price_settings_from_json", "source", self._source_loaded,
                               arguments={"silent": True, "first_load": first_load})

    def _observe_price_file(self):
        if not self._io_enabled():
            return super()._observe_price_file()
        return self.active_price_config  # A completed observation was delivered before calculate.

    def calculate(self, notify=True):
        if not self._io_enabled():
            return super().calculate(notify=notify)
        def observed(value, revision, task):
            if revision == self.quote_session.state.revision:
                super(BackgroundApplicationMixin, self).calculate(notify=notify)
            else:
                self.set_feedback("输入已变化，本次读取不覆盖草稿；请重新计算。")
        return self._submit_io("observe", "source", observed)

    def confirm_current_prices(self):
        if not self._io_enabled():
            return super().confirm_current_prices()
        revision = self.quote_session.state.revision
        self.show_price_changes()
        if revision != self.quote_session.state.revision:
            return False
        return self._submit_io("confirm", "source", lambda ok, rev, task: self.set_feedback(
            "当前价格已确认，可导出或截图。" if ok and rev == self.quote_session.state.revision else "请核对价格并重新计算。"), arguments=(revision,))

    def _simple_write(self, operation, arguments=None):
        def done(value, revision, task):
            if value:
                self.refresh_excel_files()
        return self._submit_io(operation, "write", done, write=True, arguments=arguments or {})

    def save_settings(self):
        return self._simple_write("save_settings") if self._io_enabled() else super().save_settings()
    def apply_connection(self):
        return self._simple_write("apply_connection") if self._io_enabled() else super().apply_connection()
    def apply_export_dir(self):
        return self._simple_write("apply_export_dir") if self._io_enabled() else super().apply_export_dir()
    def import_legacy_directories(self):
        return self._submit_io("import_legacy_directories", "source", lambda *_: None, arguments={}) if self._io_enabled() else super().import_legacy_directories()

    def export_to_excel(self):
        if not self._io_enabled():
            return super().export_to_excel()
        def saved(path, revision, task):
            if path:
                self.set_feedback("Excel已保存：" + str(path))
                self.refresh_excel_files()
        return self._submit_io("excel", "write", saved, write=True)

    def _capture_current_quote(self):
        if not self._io_enabled():
            return super()._capture_current_quote()
        decision = self.quote_session.prepare_output("screenshot")
        if not decision.allowed or self._blocking_file_request or self._io_runtime.writing:
            self.set_feedback("截图暂不可保存，请完成计算、价格确认和上次写入核查。", is_error=True)
            return False
        from PIL import ImageGrab
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        try:
            image = ImageGrab.grab(bbox=(x, y, x + self.root.winfo_width(), y + self.root.winfo_height()))
        except Exception as exc:
            self.set_feedback("屏幕截取失败：" + str(exc), is_error=True)
            return False
        return self._submit_io("screenshot", "write", lambda path, rev, task: self.set_feedback(
            "截图已保存：" + str(path)) if path else None, write=True, arguments=(image,))

    def check_last_write(self):
        if not self._io_enabled():
            return super().check_last_write()
        if self._io_runtime.writing:
            self.set_feedback("写入仍进行中，提交尚未确认；请等待原任务结果。")
            return False
        return self._submit_io("check_last_write", "query", lambda value, rev, task: self._refresh_saved_order()
            if value and value["status"] == "committed" else None, arguments={})

    def _edit_order(self, operation, remark=None, *, reason=None, target=None):
        if not self._io_enabled():
            return super()._edit_order(operation, remark, reason=reason, target=target)
        current = self._edit_target()
        if target is not None and current != target:
            raise ValueError("确认期间选中订单已变化，请重新确认")
        def saved(value, revision, task):
            if not value:
                return
            if operation == "append_remark" and getattr(self, "_remark_editor_order", None) == (str(Path(current[0]).absolute()), current[1]):
                if self.excel_remark_text.get("1.0", "end").strip() == remark:
                    self.excel_remark_text.delete("1.0", "end")
                    self._remark_drafts.pop(self._remark_editor_order, None)
            elif operation != "append_remark" and self.excel_order_reason.get().strip() == reason:
                self.excel_order_reason.set("")
            self._refresh_saved_order()
        return self._submit_io("edit", "write", saved, write=True,
            arguments=((operation, remark), {"reason": reason, "target": current}))

    def save_current_excel_remark(self):
        if not self._io_enabled():
            return super().save_current_excel_remark()
        try:
            text = self.excel_remark_text.get("1.0", "end").strip()
            if not text or len(text) > 4096:
                raise ValueError("请输入1至4096字符的追加备注")
            return self._edit_order("append_remark", text)
        except Exception as exc:
            self.set_feedback("备注未提交：" + str(exc), is_error=True)
            return False

    def _confirm_order_state(self, operation):
        if not self._io_enabled():
            return super()._confirm_order_state(operation)
        from tkinter import messagebox
        label = "作废" if operation == "void_order" else "恢复"
        try:
            target = self._edit_target()
            view = self._excel_order_views[target[1]]
            if view.state != ("active" if operation == "void_order" else "void"):
                raise ValueError("选中订单状态不适用于本操作")
            reason = self.excel_order_reason.get().strip()
            if not reason or len(reason) > 4096:
                raise ValueError("请填写1至4096字符的操作原因")
            if not messagebox.askyesno(label + "选中订单", f"订单：{target[1]}\n版本：{target[2]}\n文件：{Path(target[0]).name}\n原因：{reason}\n保留原记录；金额将{'移出' if operation == 'void_order' else '计入'}有效汇总。确认{label}？"):
                self.set_feedback("已取消，文件未改动。")
                return False
            return self._edit_order(operation, reason=reason, target=target)
        except Exception as exc:
            self.set_feedback(label + "未提交：" + str(exc), is_error=True)
            return False

    def _refresh_saved_order(self):
        committed = self.last_file_transaction
        if committed and str(Path(self.current_excel_path or "").absolute()) == str(Path(committed.path).absolute()):
            self._io_reselect = committed.result.get("order_id")
            self.load_current_excel_sheet()
        self.refresh_excel_files()

    def cancel_background_reads(self):
        self._assert_io_owner()
        self._io_epoch += 1
        self._io_runtime.cancel_reads()
        self._io_render_task = None
        self._io_files_token = None
        self._io_starting = False
        previous = getattr(self, "_io_last_view", None)
        if previous and not self._io_closing:
            self._render_io_view(previous, object())
        previous_files = getattr(self, "_io_last_files", None)
        if previous_files is not None and not self._io_closing:
            self._render_io_files(previous_files, object())
        self.background_status_var.set("已请求取消读取，保留上次显示；正在进行的I/O不保证已终止。")

    def on_close(self):
        if not self._io_enabled():
            return super().on_close()
        self._io_closing = True
        self.cancel_background_reads()
        if self._io_runtime.writing:
            self.background_status_var.set("正在关闭：等待原写任务交付提交状态；界面仍响应，请勿重复保存。")
        else:
            self._destroy_after_io()

    def _destroy_after_io(self):
        self._io_runtime.close()
        self.root.after_cancel(self._io_poll_job)
        self._io_callbacks.clear()
        super().on_close()

    def ensure_directories(self):
        if not self._io_enabled():
            return super().ensure_directories()
        # Only the worker transaction creates/probes output folders.
        return None

    def refresh_excel_files(self):
        if not self._io_enabled():
            return super().refresh_excel_files()
        if self._io_starting or not self.data_root:
            return False
        self._io_files_token = None
        return self._submit_io("scan", "files", lambda results, rev, task: self._render_io_files(results, task))

    def aggregate_all_excels(self, silent=False):
        if not self._io_enabled():
            return super().aggregate_all_excels(silent=silent)
        def totals(results, revision, task):
            self._aggregate_results(results, silent=True, render=False)
            self._render_io_files(results, task)
        return self._submit_io("scan", "files", totals)

    def _render_io_files(self, results, task):
        self.excel_read_results = results
        self._io_files_token = task
        tree = self.excel_file_tree
        tree.delete(*tree.get_children())
        rows = list(results.items())
        epoch = self._io_epoch
        def batch(start=0):
            if self._io_closing or epoch != self._io_epoch or self._io_files_token is not task:
                return
            for path, (result, modified) in rows[start:start + 100]:
                self._insert_excel_file(path, result, modified)
            if start + 100 < len(rows):
                self.schedule_quote_callback(lambda: batch(start + 100), delay=1)
            else:
                self._io_last_files = results
        batch()

    def open_excel_path(self, path):
        if not self._io_enabled():
            return super().open_excel_path(path)
        return self._request_io_view(path, None)

    def load_current_excel_sheet(self):
        if not self._io_enabled():
            return super().load_current_excel_sheet()
        if not self.current_excel_path:
            return False
        return self._request_io_view(self.current_excel_path, self.excel_sheet_var.get().strip())

    def _request_io_view(self, path, sheet):
        self._io_render_task = None
        self._excel_view_hash = self._excel_view_path = None
        self._excel_view_orders = {}
        return self._submit_io("view", "view", lambda view, rev, task: self._render_io_view(view, task), arguments=(path, sheet))

    def _render_io_view(self, view, token):
        self._io_render_task = token
        self.current_excel_path = view.path
        self.excel_selected_file.set(view.path)
        self.excel_sheet_combo.configure(values=view.sheets)
        self.excel_sheet_var.set(view.sheet)
        tree = self.excel_view_tree
        tree.delete(*tree.get_children())
        columns = tuple(f"c{i}" for i in range(len(view.headings)))
        tree.configure(columns=columns, show="headings")
        for column, heading in zip(columns, view.headings):
            tree.heading(column, text=heading)
            tree.column(column, width=140, anchor="w")
        self.excel_view_row_map = {}
        self._excel_view_orders = {}
        epoch = self._io_epoch
        self.show_excel_detail()
        def batch(start=0):
            if self._io_closing or epoch != self._io_epoch or self._io_render_task is not token:
                return
            for row, values in view.rows[start:start + 100]:
                item = f"row_{row}"
                tree.insert("", "end", iid=item, values=values)
                self.excel_view_row_map[item] = row
            if start + 100 < len(view.rows):
                self.schedule_quote_callback(lambda: batch(start + 100), delay=1)
                return
            self._excel_view_orders = view.identities
            self._excel_order_views = view.orders
            self._excel_view_hash = view.ledger.source_sha256
            self._excel_view_path = view.path
            if view.ledger.status == "ok":
                self._io_last_view = view
            self.set_feedback(self._read_status(view.ledger), is_error=view.ledger.status != "ok")
            if self.quote_role == "manager":
                order_id = getattr(self, "_io_reselect", None)
                if order_id:
                    self.select_excel_order(order_id)
                    self._io_reselect = None
                else:
                    self.load_current_excel_remark()
        batch()
