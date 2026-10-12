"""Owner-thread presentation of typed workbook reads; no writes or money floats."""
from decimal import Decimal
import os
import time
from tkinter import messagebox
from weakref import WeakKeyDictionary

from quote_core.numbers import money_text, rounded_ratio, settle
from quote_files.reading import analyze, read_ledger
from quote_files.schema import table_header
from quote_files.transactions import read_bytes
from quote_files.workbooks import open_book


class FileReadingMixin:
    def open_excel_for_view(self, path):
        self._excel_view_hash = None
        self._excel_view_orders = {}
        self._excel_view_path = None
        self._excel_order_views = {}
        return open_book(read_bytes(path), for_write=False)

    def _excel_cell_text(self, value, money=False):
        if value is None:
            return ""
        if money and type(value) in (int, float, Decimal, str):
            try:
                amount = Decimal(str(value))
                if amount.is_finite():
                    return money_text(settle(amount))
            except Exception:
                pass
        return str(value)

    def parse_excel_summary(self, path):
        return read_ledger(path)

    def count_visible_excel_rows(self, path):
        return read_ledger(path)

    def read_excel_remark(self, path):
        result = read_ledger(path)
        if result.status != "ok":
            self.set_feedback("文件说明读取失败：" + self._read_status(result), is_error=True)
            return ""
        return result.remark

    @staticmethod
    def find_excel_table_header(ws):
        try:
            return table_header(ws)
        except Exception:
            return None, {}

    def _remember_ledger(self, book, result):
        if not hasattr(self, "_ledger_views"):
            self._ledger_views = WeakKeyDictionary()
        self._ledger_views[book] = result

    def _ledger_for_sheet(self, ws):
        if not hasattr(self, "_ledger_views") or ws.parent not in self._ledger_views:
            self._remember_ledger(ws.parent, analyze(ws.parent))
        return self._ledger_views[ws.parent]

    def sales_record_visible(self, ws, headers, row):
        result = self._ledger_for_sheet(ws)
        return result.status == "ok" and row in result.visible_rows

    def sales_group_key(self, ws, headers, row):
        return self._ledger_for_sheet(ws).group_keys.get(row, ("unresolved", row))

    def build_group_sales_totals(self, ws, headers, header_row):
        result = self._ledger_for_sheet(ws)
        if result.status != "ok":
            raise ValueError(self._read_status(result))
        return result.group_totals

    @staticmethod
    def _read_status(result):
        if result.status != "ok":
            prefix = "读取失败" if result.status == "error" else "格式不支持"
            return prefix + "：" + "; ".join(i.message for i in result.issues)
        warnings = [i.message for i in result.issues]
        text = "可读取" if result.schema.writable else "可读取（只读）"
        return text + ("；" + "; ".join(dict.fromkeys(warnings)) if warnings else "")

    def _scan_excel_files(self):
        results = {}
        for path in self.get_report_excel_paths():
            result = read_ledger(path)
            try:
                modified = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path)))
            except OSError:
                modified = "无法获取"
            results[path] = (result, modified)
        self.excel_read_results = results
        return results

    def _render_excel_files(self, results):
        if not hasattr(self, "excel_file_tree"):
            return
        self.excel_file_tree.delete(*self.excel_file_tree.get_children())
        for path, (result, modified) in results.items():
            self._insert_excel_file(path, result, modified)

    def _insert_excel_file(self, path, result, modified):
        status = self._read_status(result)
        if self.quote_role == "sales":
            count = result.detail_count if result.status == "ok" else "—"
            values = (os.path.basename(path), modified, count, status)
        else:
            values = {"income": "—", "cost": "—", "profit": "—", "margin": "—"}
            if result.status == "ok":
                values = result.totals.display()
            values = (os.path.basename(path), modified, values["income"], values["cost"],
                      values["profit"], values["margin"] or "—", result.remark, status)
        self.excel_file_tree.insert("", "end", iid=path, values=values)

    def refresh_excel_files(self):
        if not hasattr(self, "excel_file_tree"):
            return
        try:
            self._render_excel_files(self._scan_excel_files())
        except Exception as exc:
            self.set_feedback("文件列表读取失败：" + str(exc), is_error=True)

    def aggregate_all_excels(self, silent=False):
        try:
            results = self._scan_excel_files()
        except Exception as exc:
            self.excel_total_count.set("读取失败")
            for name in ("income", "cost", "profit", "margin"):
                getattr(self, "excel_total_" + name).set("—")
            self.set_feedback("统算失败：" + str(exc), is_error=True)
            return None
        return self._aggregate_results(results, silent=silent)

    def _aggregate_results(self, results, silent=False, render=True):
        good = [r for r, _ in results.values() if r.status == "ok"]
        errors = sum(r.status == "error" for r, _ in results.values())
        unsupported = sum(r.status == "unsupported" for r, _ in results.values())
        partial = bool(errors or unsupported)
        label = f"{len(good)} 个文件" + (f"（部分：失败{errors}，不支持{unsupported}）" if partial else "")
        self.excel_total_count.set(label)
        income = sum(r.totals.income_cents for r in good)
        cost = sum(r.totals.cost_cents for r in good)
        amounts = {"income": money_text(income), "cost": money_text(cost), "profit": money_text(income - cost)}
        margin = None if not income else rounded_ratio((income - cost) * 100, income, 1)
        text = "—" if margin is None else ("-" if margin < 0 else "") + f"{abs(margin)//10}.{abs(margin)%10}%"
        amounts["margin"] = text
        if partial and not good:
            amounts = {key: "—" for key in amounts}
        for key, value in amounts.items():
            getattr(self, "excel_total_" + key).set(value)
        if render:
            self._render_excel_files(results)
        self.set_feedback("统算：" + label, is_error=partial)
        if not silent:
            messagebox.showinfo("部分统算" if partial else "统算完成", label + "；金额仅包含读取成功的文件。")
        return {"status": "partial" if partial else "ok", "valid_files": len(good),
                "errors": errors, "unsupported": unsupported, "income_cents": income,
                "cost_cents": cost, "profit_cents": income - cost}
