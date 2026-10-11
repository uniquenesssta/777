"""P03-01: two Windows PCs, one marked synthetic directory on a real UNC share.

Prepare creates a new directory; launch never selects production defaults.
Verify reads test workbooks only. No network interruption, restore or cleanup.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import socket
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import baseline_check
import p02_gui_check as gui
from quote_app.projection import RECORD_COLUMNS
from quote_files.transactions import digest, file_lock, read_bytes, write_exclusive
from quote_files.workbooks import open_book, receipts, writable

PROTOCOL = "777-p03-shared-test-v1"
PREFIX = "P03-test-"
FIXTURE = {"export_dir": "reports", "screenshot_dir": "screenshots", "items": [
    {"name": "共享测试商品", "sale": "10", "cost": "4", "k": "1", "single": True},
]}
CONFIG = (json.dumps(FIXTURE, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
HEADERS = ("记录时间", "淘宝ID", "订单号", "微信号", *RECORD_COLUMNS)


def fingerprints():
    paths = [*ROOT.glob("quote_core/*.py"), *ROOT.glob("quote_app/*.py"),
             *ROOT.glob("quote_files/*.py"), *ROOT.glob("报价*.py"),
             Path(__file__), ROOT / "tools/p02_gui_check.py", ROOT / "tools/baseline_check.py"]
    return {p.relative_to(ROOT).as_posix(): digest(p.read_bytes().replace(b"\r\n", b"\n"))
            for p in sorted(paths)}


def ordinary(path, *, directory=False):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ValueError("测试目录拒绝链接、重解析点及非普通文件")


def prepare(parent):
    parent = Path(parent).absolute()
    ordinary(parent, directory=True)
    token = str(uuid.uuid4())
    sandbox = parent / (PREFIX + token)
    sandbox.mkdir()  # Exclusive new child; never reuse config.json or 利润表.
    for name in ("reports", "screenshots", "sessions"):
        (sandbox / name).mkdir()
    write_exclusive(sandbox / "config.json", CONFIG)
    from quote_files.settings import encode_settings
    write_exclusive(sandbox / "storage.json", encode_settings({"schema": "777-shared-v1", "price_file": "config.json", "export_dir": "reports", "screenshot_dir": "screenshots"}, "shared"))
    marker = {"protocol": PROTOCOL, "sandbox_id": token,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "created_by_host": socket.gethostname(), "implementation_sha256_LF": fingerprints()}
    write_exclusive(sandbox / "p03-test.json", json.dumps(marker, ensure_ascii=False, indent=2).encode("utf-8"))
    return sandbox


def validate(sandbox):
    sandbox = Path(sandbox).absolute()
    ordinary(sandbox, directory=True)
    ordinary(sandbox / "p03-test.json")
    marker = json.loads(read_bytes(sandbox / "p03-test.json"))
    token = marker["sandbox_id"]
    if (marker.get("protocol") != PROTOCOL or str(uuid.UUID(token)) != token
            or sandbox.name != PREFIX + token):
        raise ValueError("不是本工具新建的P03共享测试目录；拒绝访问")
    if marker["implementation_sha256_LF"] != fingerprints():
        raise ValueError("两端测试代码指纹不同；两台电脑git pull后创建新测试目录")
    for name in ("reports", "screenshots", "sessions"):
        ordinary(sandbox / name, directory=True)
    if read_bytes(sandbox / "config.json") != CONFIG:
        raise ValueError("测试配置缺失或已改变；不重建、不覆盖，请创建新测试目录")
    return sandbox, marker


def workbook_paths(sandbox):
    paths = sorted((sandbox / "reports").glob("利润明细_*.xlsx"))
    if not paths or len(paths) > 3:
        raise ValueError("应有1至3份测试日工作簿；先导出，测试尽量在同一天完成")
    for path in paths:
        ordinary(path)
    return paths


def verify(sandbox, expected_orders, expected_voids=0):
    sandbox, marker = validate(sandbox)
    orders, references, request_ids = set(), set(), set()
    counts = {"orders": 0, "active": 0, "void": 0, "append_receipts": 0,
              "remark_receipts": 0, "void_receipts": 0}
    files = []
    for path in workbook_paths(sandbox):
        raw = read_bytes(path)
        book = open_book(raw)
        try:
            ws, header_row, headers = writable(book, HEADERS)
            log = receipts(book)
            groups = {}
            for index in range(header_row + 1, ws.max_row + 1):
                if all(cell.value is None for cell in ws[index]):
                    continue
                value = lambda key: ws.cell(index, headers[key]).value
                oid, rid, ref = value("订单ID"), value("请求ID"), value("订单号")
                if not oid or not ref or rid not in log or log[rid]["order_id"] != oid:
                    raise ValueError("测试订单编号/订单号/追加回执不完整")
                group = groups.setdefault(oid, {"rid": rid, "ref": ref,
                    "state": value("记录状态"), "kinds": []})
                if group["ref"] != ref:
                    raise ValueError("同单订单号不一致")
                kind = value("行类型")
                group["kinds"].append(kind)
                if tuple(str(value(key)) for key in ("销售额", "总成本", "利润")) != ("10.00", "4.00", "6.00"):
                    raise ValueError("只允许每单1件、售价10/成本4/利润6的测试数据")
                if kind == "normal" and (value("基础类型") != "共享测试商品" or str(value("数量")) != "1"):
                    raise ValueError("测试商品/数量不符")
            for oid, group in groups.items():
                if sorted(group["kinds"]) != ["normal", "order_total"]:
                    raise ValueError("每单必须是一条商品及一条订单总计")
                if oid in orders or group["ref"] in references:
                    raise ValueError("跨文件订单身份或人工测试订单号重复")
                orders.add(oid)
                references.add(group["ref"])
                counts["orders"] += 1
                counts[group["state"]] += 1
            operations = {row[0]: row[1] for row in book["_写入事务"].iter_rows(min_row=2, values_only=True)}
            append_ids = {rid for rid, op in operations.items() if op == "append_quote"}
            if append_ids != {group["rid"] for group in groups.values()}:
                raise ValueError("追加回执与订单不一一对应")
            for rid, operation in operations.items():
                if rid in request_ids or log[rid]["order_id"] not in groups:
                    raise ValueError("跨文件请求重复或回执指向缺失订单")
                request_ids.add(rid)
                counts[{"append_quote": "append_receipts", "append_remark": "remark_receipts", "void_order": "void_receipts"}[operation]] += 1
            active = sum(group["state"] == "active" for group in groups.values())
            expected = (f"{active * 10}.00", f"{active * 4}.00", f"{active * 6}.00")
            actual = tuple(str(ws.cell(4, col).value) for col in (2, 4, 6))
            if actual != expected:
                raise ValueError(f"日汇总不符：{actual}，预期{expected}")
            files.append({"path": str(path), "sha256": digest(raw), "orders": len(groups),
                          "active": active, "summary": actual, "request_ids": sorted(log)})
        finally:
            book.close()
    if counts["orders"] != expected_orders or counts["void"] != expected_voids:
        raise ValueError(f"订单数不符：{counts}；预期总单{expected_orders}/作废{expected_voids}")
    sessions = []
    for path in sorted((sandbox / "sessions").glob("*.json")):
        ordinary(path)
        session = json.loads(read_bytes(path))
        if session["sandbox_id"] != marker["sandbox_id"] or session["implementation_sha256_LF"] != fingerprints():
            raise ValueError("窗口报告与本次测试不匹配")
        sessions.append({"host": session["host"], "role": session["role"],
                         "status": session["status"], "path": str(path)})
    return {"counts": counts, "files": files, "order_refs": sorted(references), "sessions": sessions,
            "recorded_hosts": sorted({s["host"] for s in sessions}),
            "scope": "只读核对测试订单/回执/金额；主机数与并发操作仍须用户确认"}


def observed_type(parent, events):
    """Record write boundaries without changing application retries or prompts."""
    class Observed(parent):
        def _record(self, operation, pending, error=None):
            req = pending["request"] if pending else None
            event = {"at": datetime.now(timezone.utc).isoformat(), "operation": operation,
                     "request_id": req.request_id if req else None,
                     "order_id": req.order_id if req else None,
                     "status": "unconfirmed" if error else "committed"}
            if error:
                event["error"] = f"{type(error).__name__}: {error}"
            else:
                committed = getattr(self, "last_file_transaction", None)
                event["already_committed"] = committed.already_committed if committed and committed.request_id == event["request_id"] else None
            events.append(event)

        def _write_quote_excel(self, payload):
            try:
                path = super()._write_quote_excel(payload)
            except Exception as exc:
                self._record("append_quote", self._excel_pending, exc)
                raise
            self._record("append_quote", self._excel_pending)
            return path

        def _edit_order(self, operation, remark=None):
            try:
                result = super()._edit_order(operation, remark)
            except Exception as exc:
                self._record(operation, self._edit_pending, exc)
                raise
            self._record(operation, self._edit_pending)
            return result
    return Observed


def launch(sandbox, role, report):
    import tkinter as tk
    sandbox, marker = validate(sandbox)
    report.update(role=role, sandbox_id=marker["sandbox_id"], events=[])
    ns, _ = gui.load_namespace(ROOT, role, sandbox)
    window = tk.Tk()
    errors = gui.track_callback_errors(window)
    try:
        app = observed_type(gui.live_sandbox_type(ns, sandbox), report["events"])(window)
        window.title(f"P03共享测试 | {socket.gethostname()} | {role}")
        app.user_name.set("P03共享测试")
        app.add_calc_row("共享测试商品", "共享测试商品", True)
        print(f"仅测试目录：{sandbox}\n关闭后保留测试文件；请勿修改价格和目录。", file=sys.stderr)
        window.mainloop()
        report["status"] = "manual_session_finished; user_observation_required"
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        try:
            window.destroy()
        except tk.TclError:
            pass
        gui.finish_callbacks(window, report, errors)
        session = sandbox / "sessions" / (str(uuid.uuid4()) + ".json")
        report["session_report"] = str(session)
        write_exclusive(session, json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))


def hold(sandbox, seconds):
    sandbox, _ = validate(sandbox)
    paths = workbook_paths(sandbox)
    if len(paths) != 1:
        raise ValueError("持锁测试只接受一份当日测试工作簿")
    path = paths[0]
    with file_lock(path):
        before = digest(read_bytes(path))
        print(f"已持有测试工作簿锁{seconds}秒：{path}\n请另一台电脑立即导出。不要删除锁文件。", file=sys.stderr, flush=True)
        time.sleep(seconds)
        after = digest(read_bytes(path))  # Still holding the lock; no post-release race.
        if before != after:
            raise ValueError("持锁期间原件发生改变；停止验收并保留文件")
    return {"path": str(path), "seconds": seconds, "before_sha256": before,
            "while_locked_sha256": after, "lock_released": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", type=Path, metavar="UNC_PARENT")
    mode.add_argument("--launch", choices=("manager", "sales"))
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--hold-lock", action="store_true")
    parser.add_argument("--sandbox", type=Path)
    parser.add_argument("--expected-orders", type=int)
    parser.add_argument("--expected-voids", type=int, default=0)
    parser.add_argument("--seconds", type=int, choices=range(10, 61), default=30, metavar="10..60")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.prepare and not args.sandbox:
        parser.error("本模式需要 --sandbox 新建的测试目录")
    if args.verify and (args.expected_orders is None or not 0 <= args.expected_voids <= args.expected_orders <= 100):
        parser.error("核对需要 --expected-orders 0..100 及有效 --expected-voids")
    if args.output and args.output.exists():
        parser.error("报告已存在；请换 --output 文件名，不覆盖旧报告")
    report = {"task": "P03-01", "host": socket.gethostname(), "pid": os.getpid(),
              "environment": {"os": platform.system(), "python": platform.python_version()},
              "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "implementation_sha256_LF": fingerprints(), "status": "started",
              "production_paths_accessed": False, "shared_acceptance": "user_observation_pending",
              "scope": "同一真实共享盘的新建合成目录；不执行断网、恢复或删除"}
    try:
        if platform.system() != "Windows":
            report.update(status="blocked", reason="请在两台实际Windows电脑运行；合成测试不替代SMB验收")
        else:
            chosen = args.prepare or args.sandbox
            if not str(chosen).startswith("\\\\") or str(chosen).startswith("\\\\?\\"):
                raise ValueError("使用完整普通UNC共享路径，两端不要混用E盘或映射盘")
            if args.prepare:
                report.update(sandbox=str(prepare(args.prepare)), status="prepared")
            elif args.launch:
                launch(args.sandbox, args.launch, report)
            elif args.verify:
                report.update(checks=verify(args.sandbox, args.expected_orders, args.expected_voids), status="data_checks_passed")
            else:
                report.update(checks=hold(args.sandbox, args.seconds), status="lock_hold_completed")
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    baseline_check.emit(report, args.output)
    return 2 if report["status"] == "blocked" else int(report["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
