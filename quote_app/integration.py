"""Shared owner-thread controller for the existing manager/sales Tk entrypoints.

Files/Tk/Pillow/openpyxl live here or in the existing format/view adapters, never
in quote_core. Local config SHA identifies bytes, not authenticated publication.
P03 handles atomic file writes/concurrency; P05 handles service authority.
"""
import hashlib
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import time
import uuid
from tkinter import TclError, filedialog, messagebox, ttk

from quote_core import (
    Amounts, DraftDetails, Issue, OutputBlocked, QuoteSession,
    ValidationError, capture_legacy_quote, parse_percent, parse_price_config,
)
from quote_core.configuration import CONFIG_BYTE_LIMIT
from quote_core.numbers import exact_context, settle

from .projection import append_quote, legacy_record
from .storage import resolve_directory
from .connections import ConnectionMixin
from .file_edits import FileEditingMixin
from .file_reads import FileReadingMixin
from quote_files.configuration import save_config
from quote_files.transactions import FileFailure, UnknownCommit, digest, query_request
from quote_files.workbooks import assign_order, inspect_receipt, request, workbook_transaction
from quote_files.schema import DETAIL_HEADERS, create_template


FIELD_NAMES = {"q": "数量", "h": "高度", "w": "宽度", "sale": "销售单价",
               "cost": "成本单价", "k": "K系数", "percent": "折扣",
               "product_id": "项目类型", "price_source": "价格来源"}
REASONS = {
    "CALCULATION_REQUIRED": "输入已变化，请重新计算。",
    "PRICE_VERSION_CHANGED": "价格已更新，请刷新、查看差异、重算并确认。",
    "PRICE_CONFIRMATION_REQUIRED": "请查看价格差异，重算后确认当前价格。",
    "PRICES_UNAVAILABLE": "价格文件暂不可用，当前金额只供草稿预览。",
    "PRICE_SOURCE_UNVERIFIED": "当前使用未保存的价格，保存有效配置后刷新。",
    "PRICE_CONFIG_INVALID": "价格配置校验失败，当前金额只供草稿预览。",
    "DIRECTORY_CONFIG_INVALID": "共享目录无效，请在母版重新保存；本机盘符不能直接发给子版。",
    "PRODUCT_NOT_FOUND": "项目已不存在，请删除或重新选择。",
    "LINE_CAPACITY": "请添加项目；订单最多支持10000行。",
    "DISCOUNT_ZERO_SUBTOTAL": "折扣前小计为零，请确认折扣行位置。",
    "EMPTY": "请输入数值。", "SYNTAX": "数值或表达式格式错误。",
    "FIELD_RANGE": "数值须为非负且不超过1000000000。",
    "FIELD_SCALE": "小数位数超过12位。", "DIVISION_BY_ZERO": "表达式除数不能为零。",
    "DISCOUNT_SYNTAX": "请输入0至100之间的百分比。",
    "DISCOUNT_CAPACITY": "百分比长度或精度超出范围。",
    "PRICE_EDITOR_INVALID": "请修正重复、空白或保留的商品名称。",
}


def price_version(source):
    return "local-sha256:" + hashlib.sha256(source).hexdigest()


def config_mapping(prices):
    return {p.product_id: {"sale": p.sale, "cost": p.cost, "k": p.k, "single": p.single}
            for p in prices.items}


def price_difference(old, new):
    """User-facing difference excludes costs in the sales projection."""
    a, b = config_mapping(old) if old else {}, config_mapping(new)
    return tuple((name, a.get(name), b.get(name)) for name in sorted(a.keys() | b.keys())
                 if a.get(name) != b.get(name))


class QuoteApplicationMixin(ConnectionMixin, FileReadingMixin, FileEditingMixin):
    quote_role = "manager"

    def initialize_quote_state(self):
        self.quote_session = QuoteSession()
        self.active_price_config = None
        self.price_changes = ()
        self._loading_prices = False
        self._config_load_problem = None
        self._storage_version = None
        self._after_jobs = set()
        self._excel_pending = None
        self._config_pending = None
        self._edit_pending = None
        self._blocking_file_request = None
        self.last_file_transaction = None
        self._excel_view_hash = None
        self._excel_view_orders = {}
        self._excel_view_path = None
        self._last_config_sha = None
        self.initialize_connections()

    def schedule_quote_callback(self, callback, *, delay=None):
        def run():
            self._after_jobs.discard(job)
            callback()
        job = self.root.after_idle(run) if delay is None else self.root.after(delay, run)
        self._after_jobs.add(job)
        return job

    def choose_storage_dir(self, var):
        if self.quote_role != "manager":
            return False
        path = filedialog.askdirectory(parent=self.root, initialdir=var.get())
        if path:
            var.set(path)
        return bool(path)

    def choose_export_dir(self):
        return self.choose_storage_dir(self.export_dir_var)

    def reset_export_dir_to_local(self):
        if self.quote_role != "manager":
            return False
        self.export_dir_var.set(resolve_directory(None, self._price_path(), "利润表"))
        return self.apply_export_dir()

    def install_quote_controls(self):
        for var in (self.user_name, self.order_no, self.wechat_no):
            var.trace_add("write", self.quote_input_changed)
        box = ttk.Frame(self.calc_page, padding=(12, 0, 12, 6))
        box.pack(fill="x")
        self.quote_status_var = self._new_text_var("请添加项目并计算。")
        ttk.Label(box, textvariable=self.quote_status_var, wraplength=900).pack(side="left", fill="x", expand=True)
        ttk.Button(box, text="查看价格差异", command=self.show_price_changes).pack(side="left", padx=4)
        ttk.Button(box, text="确认当前价格", command=self.confirm_current_prices).pack(side="left", padx=4)
        if self.quote_role == "manager":
            ttk.Button(box, text="刷新已保存价格", command=self.reload_price_settings_from_json).pack(side="left", padx=4)
        self.update_quote_status()
        if not self.data_root:
            self.notebook.select(self.excel_page)
            self.set_feedback("首次使用：在Excel记录页选择数据源并保存本机连接；母版再保存共享目录。")

    def _new_text_var(self, text):
        # Entry modules already own the interpreter; no implicit default root.
        from tkinter import StringVar
        return StringVar(master=self.root, value=text)

    def watch_quote_row(self, row, *, settings=False):
        keys = ("name", "sale", "cost", "k", "single") if settings else (
            "q", "h", "w", "discount_choice", "discount_custom")
        for key in keys:
            if key in row:
                row[key].trace_add("write", self.quote_input_changed)
        if not self._loading_prices:
            self.quote_input_changed()

    def clear_quote_display(self):
        self.last_export_records = []  # Compatibility/display only, never authority.
        for row in self.calc_rows:
            row["res"].set("—")
            row["status"].set("待重算")
        if hasattr(self, "profit_tree"):
            for item in self.profit_tree.get_children():
                self.profit_tree.delete(item)
        self.total_val.set("总计：待计算")
        for name in ("summary_income", "summary_cost", "summary_profit", "summary_margin"):
            getattr(self, name).set("—")

    def quote_input_changed(self, *_):
        if self._loading_prices:
            return
        self.quote_session.invalidate_inputs()
        self.clear_quote_display()
        self.update_quote_status()

    def update_quote_status(self):
        if not hasattr(self, "quote_status_var"):
            return
        state = self.quote_session.state
        decision = self.quote_session.prepare_output("excel")
        text = ("目录尚未确认，请在Excel记录页保存或修复连接。" if not self._storage_valid else
                "计算有效，可导出或截图。" if decision.allowed else self._issue_text(decision.issues[0]))
        if state.price_confirmation_required:
            text += " 查看价格差异，重算后点击“确认当前价格”。"
        self.quote_status_var.set(text)

    @staticmethod
    def _issue_text(issue):
        field = FIELD_NAMES.get(issue.field, issue.field)
        location = f"第{issue.line_index}行 " if issue.line_index is not None else ""
        return location + field + "：" + REASONS.get(issue.reason, issue.reason)

    def _legacy_issues(self, issues):
        return [{"级别": "提醒" if i.code == "WARNING" else "错误",
                 "位置": f"计算第 {i.line_index} 行" if i.line_index else "配置/订单",
                 "字段": FIELD_NAMES.get(i.field, i.field), "输入内容": "",
                 "提示": REASONS.get(i.reason, i.reason)} for i in issues]

    def _price_path(self):
        return self.config_file

    def _read_price_candidate(self):
        try:
            with open(self._price_path(), "rb") as stream:
                source = stream.read(CONFIG_BYTE_LIMIT + 1)
            self._last_config_sha = digest(source)
        except OSError:
            return None, "unavailable", (Issue("IO_UNAVAILABLE", "PRICES_UNAVAILABLE", "price_source"),)
        candidate = parse_price_config(source, price_version_id=price_version(source),
            legacy_single_names={i["name"] for i in self.default_items if i.get("single") is True})
        if candidate.status != "ok":
            return None, "invalid", candidate.issues
        return candidate.config, "current", ()

    def _observe_price_file(self):
        self.observe_storage()
        candidate, status, issues = self._read_price_candidate()
        latest = candidate.prices.price_version_id if candidate else None
        self.quote_session.observe_price_source(status, latest_price_version_id=latest)
        self._config_load_problem = issues
        if self.quote_session.state.result is None:
            self.clear_quote_display()
        self.update_quote_status()
        return candidate

    def load_settings_to_ui(self):
        # No default-price fallback and no startup/close writes to a bad file.
        return self.reload_price_settings_from_json(first_load=True, silent=True)

    def reload_price_settings_from_json(self, silent=False, first_load=False):
        candidate = self._observe_price_file()
        if candidate is None:
            self.validation_issues = self._legacy_issues(self._config_load_problem)
            self.render_issues(self.validation_issues)
            self.set_feedback("价格读取失败；保留上次有效快照，只可编辑/预览草稿。请修复后刷新。", is_error=True)
            return False
        old = self.quote_session.state.prices
        if old != candidate.prices or not first_load:
            self.price_changes = price_difference(old, candidate.prices)
            self.quote_session.refresh_prices(candidate.prices)
        self.active_price_config = candidate
        self._replace_setting_rows(candidate.prices)
        self.last_config_snapshot = config_mapping(candidate.prices)
        self.refresh_item_selector()
        self.update_calc_row_states(self.last_config_snapshot)
        self.clear_quote_display()
        self.validation_issues = []
        self.render_issues([])
        self.update_quote_status()
        self.set_feedback("价格已载入。" + ("请查看差异、重算并确认。" if self.quote_session.state.price_confirmation_required else "请计算。"))
        return True

    def _replace_setting_rows(self, prices):
        self._loading_prices = True
        try:
            for row in self.setting_rows:
                if row.get("frame") is not None:
                    row["frame"].destroy()
            self.setting_rows = []
            for p in prices.items:
                self.add_setting_row(name=p.product_id, sale=p.sale, cost=p.cost, k=p.k, single=p.single)
        finally:
            self._loading_prices = False

    def get_settings_snapshot(self):
        # Editor drafts may contain unused blank prices; publishing remains strict.
        config, issues = {}, []
        for index, row in enumerate(self.setting_rows, 1):
            values = {key: row[key].get() for key in ("name", "sale", "cost", "k", "single")}
            name = values.pop("name").strip()
            if not name and all(not str(values[k]).strip() for k in ("sale", "cost", "k")):
                continue
            if not name or name == "折扣" or name in config or type(values["single"]) is not bool:
                self.add_issue(issues, "错误", f"价格设定第 {index} 行", "项目名称", name, "项目名称为空、重复、保留名称或单件类型无效。")
                continue
            config[name] = values
        return config, issues

    def apply_settings_to_calc(self):
        self.quote_input_changed()
        config, issues = self.get_settings_snapshot()
        self.refresh_item_selector()
        self.update_calc_row_states(config)
        self.validation_issues = issues
        self.render_issues(issues)
        self.set_feedback("编辑价格已用于草稿；正式输出前请保存完整有效配置、重算并确认。")

    def save_and_apply_settings(self):
        return self.save_settings()

    def save_settings(self):
        if self.quote_role == "sales":
            return False
        if self._blocking_file_request:
            self.set_feedback("存在待核查的旧请求，请先检查上次写入。", is_error=True)
            return False
        config, issues = self.get_settings_snapshot()
        if not self.data_root or not self.config_file:
            self.set_feedback("请先保存本机连接，再保存价格。", is_error=True)
            return False
        try:
            from quote_files.transactions import read_bytes
            existing = read_bytes(self.config_file)
            if existing is not None and parse_price_config(existing, price_version_id=price_version(existing)).status != "ok":
                raise FileFailure("现有价格配置损坏，禁止覆盖；请核查并显式恢复")
        except (OSError, FileFailure) as exc:
            self.set_feedback(str(exc), is_error=True)
            return False
        source = json.dumps({"items": [{"name": name, **item} for name, item in config.items()]},
                            ensure_ascii=False, indent=4).encode("utf-8")
        candidate = parse_price_config(source, price_version_id=price_version(source))
        if issues or candidate.status != "ok":
            self.quote_session.observe_price_source("invalid")
            self.quote_input_changed()
            self.validation_issues = issues + self._legacy_issues(candidate.issues)
            self.render_issues(self.validation_issues)
            self.set_feedback("未保存：配置须整份有效，原文件和上次有效快照已保留。", is_error=True)
            return False
        try:
            expected = self.active_price_config.prices.price_version_id.removeprefix("local-sha256:") if self.active_price_config else self._last_config_sha
            def validate(raw):
                if parse_price_config(raw, price_version_id=price_version(raw)).status != "ok":
                    raise FileFailure("配置整份校验失败")
            self.last_file_transaction, self._config_pending = save_config(self.config_file, source,
                expected_hash=expected, validator=validate, pending=self._config_pending)
        except (OSError, FileFailure) as exc:
            self._config_pending = getattr(exc, "pending_request", self._config_pending)
            if isinstance(exc, UnknownCommit):
                self._blocking_file_request = {"path": self.config_file, "request_id": getattr(exc, "blocking_request_id", None) or exc.request_id}
            self.quote_session.observe_price_source("unavailable")
            self.clear_quote_display()
            self.update_quote_status()
            self.set_feedback(f"配置未确认保存：{exc}；请求{getattr(exc, 'request_id', None) or '未进入提交'}，请先核查。", is_error=True)
            return False
        return self.reload_price_settings_from_json(silent=True)

    def on_close(self):
        # Saving prices is explicit; closing must not overwrite damaged configs.
        for job in tuple(self._after_jobs):
            try:
                self.root.after_cancel(job)
            except TclError:
                pass
        self._after_jobs.clear()
        self.root.destroy()

    def get_report_excel_paths(self):
        # Reading the list observes the shared directory without rebinding prices.
        if not self.observe_storage():
            self.set_feedback("无法确认共享目录，请修复母版目录设置后刷新。", is_error=True)
            return []
        self.ensure_directories()
        paths = [os.path.join(self.report_dir, name) for name in os.listdir(self.report_dir)
                 if not name.startswith("~$") and name.lower().endswith(".xlsx")]
        return sorted(paths, key=os.path.getmtime, reverse=True)

    def validate_discount_key(self, proposed):
        # Permit editing; numeric-v1 validates the full original text at calculate.
        return len(proposed) <= 256

    def normalize_discount_entry(self, var):
        # Validate without shortening original percentage precision on focus loss.
        try:
            parse_percent(var.get())
        except ValidationError:
            pass

    def calculate(self, notify=True):
        self._observe_price_file()  # Observe changes, never implicitly rebind prices.
        config, setting_issues = self.get_settings_snapshot()
        active = self.active_price_config
        is_bound = active is not None and config == config_mapping(active.prices)
        if not is_bound and self.quote_session.state.price_source == "current":
            self.quote_session.observe_price_source("unverified")
        version = active.prices.price_version_id if is_bound else "editor-sha256:" + hashlib.sha256(
            json.dumps(config, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        details = DraftDetails(self.user_name.get(), self.order_no.get(), self.wechat_no.get())
        capture_line = None
        try:
            if setting_issues:
                raise ValidationError("PRICE_EDITOR_INVALID", "prices")
            for index, row in enumerate(self.calc_rows, 1):
                if row.get("row_kind", "normal") == "normal" and row["base_type"] not in config:
                    capture_line = index
                    raise ValidationError("PRODUCT_NOT_FOUND", "product_id")
            snapshot, captured_prices = capture_legacy_quote(self.calc_rows, config, price_version_id=version)
            # Initial draft prices don't imply an explicit publication refresh.
            if not is_bound:
                if self.quote_session.state.prices != captured_prices:
                    self.quote_session.refresh_prices(captured_prices)
            elif self.quote_session.state.prices != active.prices:
                # Restoring an editor draft to the already bound file snapshot.
                # This does not adopt an observed newer file version implicitly.
                self.quote_session.refresh_prices(active.prices)
            self.quote_session.update_inputs(snapshot, details=details)
        except ValidationError as exc:
            self.quote_session.invalidate_inputs((Issue("VALIDATION", exc.reason, exc.field, capture_line),))
        state = self.quote_session.calculate()
        self._render_quote_result(state.result)
        self.update_quote_status()
        if state.result.status != "ok":
            self.set_feedback("计算失败，整单没有有效金额；请查看输入反馈。", is_error=True)
            if notify:
                self.notify_validation_errors(len(state.result.issues), 0)
        else:
            decision = self.quote_session.prepare_output("excel")
            self.set_feedback("计算完成。" if decision.allowed else "草稿计算完成；" + self._issue_text(decision.issues[0]), is_error=not decision.allowed)
        return state.result

    def _render_quote_result(self, result):
        self.clear_quote_display()
        issues = result.issues + result.warnings
        self.validation_issues = self._legacy_issues(issues + tuple(self._config_load_problem or ()))
        self.render_issues(self.validation_issues)
        if result.status != "ok":
            for issue in result.issues:
                if issue.line_index and issue.line_index <= len(self.calc_rows):
                    self.calc_rows[issue.line_index - 1]["status"].set("需检查")
            return
        self.last_export_records = [legacy_record(line) for line in result.lines]
        for row, line, record in zip(self.calc_rows, result.lines, self.last_export_records):
            row["res"].set(record["销售额"])
            row["status"].set("OK")
            if row.get("row_kind", "normal") != "discount":
                # Legacy discount rows alias this key to the input combobox var.
                # Rendering must never change its selection or invalidate itself.
                row["discount"].set(record["折扣"])
            if hasattr(self, "profit_tree"):
                self.profit_tree.insert("", "end", values=(record["项目名称"], record["折扣"],
                    record["销售额"], record["总成本"], record["利润"], record["利润率"]))
        totals = result.totals.display()
        self.total_val.set("总计：" + totals["income"] + " 元")
        for key in ("income", "cost", "profit", "margin"):
            getattr(self, "summary_" + key).set(totals[key] or "—")

    def show_price_changes(self):
        lines = []
        fields = ("sale", "cost", "k", "single") if self.quote_role == "manager" else ("sale", "k", "single")
        for name, old, new in self.price_changes:
            if old is None or new is None:
                lines.append(name + ("：新增项目" if old is None else "：项目已删除"))
            else:
                visible = [f"{FIELD_NAMES.get(key, '单件')} {old[key]} → {new[key]}" for key in fields if old[key] != new[key]]
                if visible:
                    lines.append(name + "：" + "；".join(visible))
        messagebox.showinfo("价格差异", "\n".join(lines) or "当前没有可显示的价格差异。")

    def confirm_current_prices(self):
        revision = self.quote_session.state.revision
        self.show_price_changes()  # Dialog finishes before confirmation/gate.
        self._observe_price_file()
        if self.quote_session.confirm_prices(expected_revision=revision):
            self.set_feedback("当前价格已确认，可导出或截图。")
        else:
            self.set_feedback("无法确认：请刷新有效价格并重新计算。", is_error=True)
        self.update_quote_status()

    def _formal_output(self, kind, writer):
        self._observe_price_file()
        if self._blocking_file_request:
            self.set_feedback("已阻止输出：存在未确认写入，请先检查上次写入。", is_error=True)
            return False
        if not self._storage_valid:
            self.set_feedback("已阻止输出：共享目录未确认，请先保存或修复目录设置。", is_error=True)
            return False
        # Manager editor modifications are drafts, even if file bytes stayed valid.
        config, issues = self.get_settings_snapshot()
        if self.quote_session.state.price_source == "current" and (
                issues or self.active_price_config is None
                or config != config_mapping(self.active_price_config.prices)):
            self.quote_session.observe_price_source("unverified")
        try:
            return self.quote_session.dispatch_output(kind, writer)
        except OutputBlocked as exc:
            self.clear_quote_display() if self.quote_session.state.result is None else None
            self.set_feedback("已阻止输出；" + self._issue_text(exc.decision.issues[0]), is_error=True)
            self.update_quote_status()
            return False

    def export_to_excel(self):
        # No implicit calculate, directory probe, workbook open or write before gate.
        try:
            path = self._formal_output("excel", self._write_quote_excel)
        except Exception as exc:
            self.set_feedback(f"Excel写入未确认：{exc}；" + (f"请求{exc.request_id}，请检查上次写入。" if getattr(exc, "request_id", None) else "请核查文件后再重试。"), is_error=True)
            return False
        if not path:
            return False
        self.set_feedback("Excel已保存：" + str(path))
        messagebox.showinfo("导出成功", str(path))
        # Refresh is after the write boundary; a view failure isn't a failed save.
        try:
            self.refresh_excel_files()
        except Exception:
            self.set_feedback("Excel已保存，但列表刷新失败；请手动刷新。", is_error=True)
        return path

    def _write_quote_excel(self, payload):
        # No dialog/event-loop yield/widget finance or identity reads in writer.
        if self._blocking_file_request:
            raise FileFailure("存在待核查的旧请求，请先检查上次写入")
        self.ensure_directories()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        path = self.get_daily_excel_path()
        pending = self._excel_pending
        if pending and pending["unknown"]:
            state = query_request(pending["path"], pending["request"].request_id, inspect_receipt)
            if state["status"] == "committed":
                pending["unknown"] = False
                if pending["revision"] != payload.revision:
                    raise FileFailure("上次请求已确认保存；本次变化尚未提交，请核对旧单后再导出")
                return pending["path"]
            if state["status"] != "not_committed":
                raise UnknownCommit("上次写入结果仍不明；请先检查上次写入", request_id=pending["request"].request_id)
            pending["unknown"] = False
        if not pending or pending["revision"] != payload.revision:
            req = request("append_quote", asdict(payload), order_id=str(uuid.uuid4()))
            pending = self._excel_pending = {"revision": payload.revision, "request": req, "path": path, "unknown": False}
        else:
            path = pending["path"]  # Retry remains bound to its original destination/day.
        req = pending["request"]
        def create():
            from openpyxl import Workbook
            book = Workbook()
            self.create_profit_sheet_template(book.active, timestamp)
            return book
        def mutate(wb, ws, headers):
            ws.cell(2, 1, "最后导出时间")
            ws.cell(2, 2, timestamp)
            for column, value in enumerate(("最近导出淘宝ID", payload.details.customer, "订单号",
                                          payload.details.order_ref, "微信号", payload.details.wechat), 1):
                ws.cell(3, column, value)
            start = ws.max_row + 1
            append_quote(ws, timestamp, payload, kind_column=headers["行类型"], headers=headers)
            assign_order(ws, start, ws.max_row, headers, req)
            self.recompute_daily_profit_summary(ws)
            self.style_daily_profit_sheet(ws)
            self.append_input_issues_sheet(wb, timestamp, payload)
            self.refresh_price_snapshot_sheet(wb, timestamp, payload, req)
            return {"order_revision": 1, "price_version_id": payload.prices.price_version_id}
        try:
            self.last_file_transaction = workbook_transaction(path, req, self.get_excel_headers(), create, mutate)
        except UnknownCommit as exc:
            pending["unknown"] = True
            if exc.request_id and exc.request_id != req.request_id:
                self._blocking_file_request = {"path": str(path), "request_id": exc.request_id}
            raise
        return self.last_file_transaction.path

    def create_profit_sheet_template(self, ws, timestamp):
        return create_template(ws, timestamp)

    def get_excel_headers(self):
        return list(DETAIL_HEADERS)

    def append_input_issues_sheet(self, wb, timestamp, payload):
        sheet = wb["输入问题"] if "输入问题" in wb.sheetnames else wb.create_sheet("输入问题")
        if sheet.max_row < 4:
            sheet.delete_rows(1, sheet.max_row)
            for values in (["输入校验反馈"], [], [], ["记录时间", "级别", "位置", "字段", "输入内容", "提示"]):
                sheet.append(values)
        issues = self._legacy_issues(payload.result.warnings)
        for issue in issues:
            sheet.append([timestamp] + [issue[key] for key in ("级别", "位置", "字段", "输入内容", "提示")])
        if not issues:
            sheet.append([timestamp, "OK", "全部", "", "", "没有发现输入问题。"])
        self.style_excel_sheet(sheet, header_row=4, freeze="A5", widths={"A": 20, "B": 10, "C": 22, "D": 18, "E": 24, "F": 70})

    def recompute_daily_profit_summary(self, ws):
        # Only the derived header is refreshed; historic detail cells stay intact.
        # Old numeric cells use their decimal text; formulas/bad amounts fail
        # explicitly rather than silently contributing zero to the new header.
        header_row, headers = self.find_excel_table_header(ws)
        if not header_row or not all(key in headers for key in ("销售额", "总成本", "项目名称")):
            raise ValueError("利润表表头不完整，未写入")
        income = cost = Decimal(0)
        context = exact_context()
        for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
            if "记录状态" in headers and row[headers["记录状态"] - 1] == "void":
                continue
            name = str(row[headers["项目名称"] - 1] or "").strip()
            kind = row[headers["行类型"] - 1] if "行类型" in headers else None
            if kind:
                if kind == "order_total":
                    continue
                if kind not in ("normal", "discount"):
                    raise ValueError("未知行类型，未写入；请核查原文件")
            elif not name or name.startswith("---") or name in ("备注", "文件备注"):
                continue  # Untagged legacy ambiguity is reviewed in P03-02.
            values = []
            for key in ("销售额", "总成本"):
                raw = row[headers[key] - 1]
                if raw is None or isinstance(raw, bool) or len(str(raw)) > 256:
                    raise ValueError("历史金额不完整，未写入；请先核查原文件")
                try:
                    value = Decimal(str(raw))
                except InvalidOperation as exc:
                    raise ValueError("历史金额格式不可识别，未写入；请先核查原文件") from exc
                if (not value.is_finite() or abs(value.as_tuple().exponent) > 60
                        or value.copy_abs() > Decimal("1000000000000000000")):
                    raise ValueError("历史金额超出范围，未写入")
                values.append(value)
            income, cost = context.add(income, values[0]), context.add(cost, values[1])
        display = Amounts(settle(income), settle(cost)).display()
        for column, value in enumerate(("总收入", display["income"], "总成本", display["cost"],
                                       "总利润", display["profit"], "综合利润率", display["margin"] or "—"), 1):
            ws.cell(4, column, value)

    def refresh_price_snapshot_sheet(self, wb, timestamp, payload, req):
        from quote_files.schema import PRICE_HISTORY_HEADERS
        history = wb["订单价格快照"] if "订单价格快照" in wb.sheetnames else wb.create_sheet("订单价格快照")
        if history.cell(1, 1).value is None:
            for column, value in enumerate(PRICE_HISTORY_HEADERS, 1):
                history.cell(1, column, value)
        for item in payload.prices.items:
            history.append([req.order_id, req.request_id, timestamp, payload.prices.price_version_id,
                payload.result.rule_version, payload.result.numeric_profile, item.product_id,
                item.sale, item.cost, item.k, "是" if item.single else "否"])
        if "价格设定" in wb.sheetnames:
            return  # Preserve the original legacy snapshot; never replace past prices.
        sheet = wb.create_sheet("价格设定")
        sheet.append(["价格设定快照", payload.prices.price_version_id, payload.result.rule_version, payload.result.numeric_profile])
        sheet.append(["最后导出时间", timestamp])
        sheet.append([])
        sheet.append(["项目名称", "销售单价原文", "成本单价原文", "K系数原文", "是否单件"])
        for item in payload.prices.items:
            sheet.append([item.product_id, item.sale, item.cost, item.k, "是" if item.single else "否"])
        self.style_excel_sheet(sheet, header_row=4, freeze="A5", widths={"A": 22, "B": 18, "C": 18, "D": 14, "E": 10})

    def save_screenshot(self):
        # Capture follows idle drawing, then rechecks the gate at callback time.
        # update()/update_idletasks() inside the writer would allow stale reentry.
        self.notebook.select(self.calc_page)
        self.schedule_quote_callback(self._capture_current_quote)

    def _capture_current_quote(self):
        try:
            path = self._formal_output("screenshot", self._write_quote_screenshot)
        except Exception as exc:
            self.set_feedback(f"截图未确认保存：{exc}" + (f"；请求{exc.request_id}，请检查上次写入。" if getattr(exc, "request_id", None) else ""), is_error=True)
            return False
        if path:
            self.set_feedback("截图已保存：" + str(path))
            messagebox.showinfo("保存成功", str(path))
        return path

    def _write_quote_screenshot(self, payload):
        # Adapter renders the frozen result when calculating; no nested event loop.
        from PIL import ImageGrab
        folder = self.get_daily_screenshot_dir() if self.quote_role == "sales" else self.image_dir
        os.makedirs(folder, exist_ok=True)
        name = self.clean_filename(payload.details.customer)
        order = self.clean_filename(payload.details.order_ref) or "未填订单号"
        path = Path(folder) / f"{name[:60]}_{order[:60]}_{time.time_ns()}_{uuid.uuid4().hex}.png"
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        image = ImageGrab.grab(bbox=(x, y, x + self.root.winfo_width(), y + self.root.winfo_height()))
        from quote_files.images import save_png
        try:
            self.last_file_transaction = save_png(path, image)
        except UnknownCommit as exc:
            self._blocking_file_request = {"path": str(path), "request_id": exc.request_id}
            raise
        return str(path)
