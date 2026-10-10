"""P01-02 review examples, not a production calculator or P01-04 golden suite.

Run from the repository root: python docs/baseline/p01_02_examples.py
Original calculations use stubbed controls and synthetic, in-memory prices.
The Decimal comparison accepts only the declared examples below; it does not
implement expression parsing, authorization, price loading, or persistence.
"""
import importlib.util
import json
from pathlib import Path
import platform
import runpy
import tempfile
from decimal import Decimal, ROUND_HALF_UP, localcontext

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("audit_examples", ROOT / "docs/audit/reproduce.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def normal(q="1", sale="10", cost="4", k="1", h="1", w="1", single=True):
    return dict(kind="normal", q=q, sale=sale, cost=cost, k=k, h=h, w=w, single=single)


def discount(percent):
    return dict(kind="discount", percent=percent)


CASES = [
    ("E01", "面积与K", [normal(q="3", sale="50", cost="20", k="1.1", h="1.2", w="0.8", single=False)], None),
    ("E02", "单件小数数量与空K", [normal(q="2.5", sale="12", cost="4", k="")], None),
    ("E03", "两行半分", [normal(sale="0.005", cost="0"), normal(sale="0.005", cost="0")], None),
    ("E04", "销售与成本分别量化后求利润", [normal(sale="1.005", cost="1.004")], None),
    ("E05", "连续折扣后加商品", [normal(sale="100", cost="60"), discount("90"), discount("80"), normal(sale="50", cost="20")], None),
    ("E06", "负折扣半分", [normal(sale="0.05", cost="0.02"), discount("90")], None),
    ("E07", "零收入但有成本", [normal(sale="0", cost="4")], None),
    ("E08", "0%表示免费", [normal(), discount("0")], None),
    ("E09", "100%表示原价", [normal(), discount("100")], None),
    ("E10", "普通行负数量", [normal(q="-1")], "普通行数量为负；候选规则阻断整单"),
    ("E11", "一行有效一行错误", [normal(), normal(q="bad")], "存在字段错误；候选规则不提交有效部分"),
    ("E12", "布尔量不作为数量", [normal(q="True")], "布尔常量不是业务数值"),
    ("E13", "有限输入乘积溢出", [normal(q="1e308", sale="1e308", cost="0")], "乘积超出结算容量；候选规则报错而非inf"),
    ("E14", "折扣在首行", [discount("90"), normal()], None),
    ("E15", "综合利润率按总额计算", [normal(sale="100", cost="90"), normal(sale="10", cost="0")], None),
    ("E16", "正输入仍可产生亏损", [normal(sale="10", cost="20")], None),
]


def original(ns, folder, lines):
    obj = audit.instance(ns, folder)
    config = {}
    obj.calc_rows = []
    for index, line in enumerate(lines, 1):
        name = "折扣" if line["kind"] == "discount" else f"商品{index}"
        values = {"q": line.get("q", ""), "h": line.get("h", ""), "w": line.get("w", ""), "discount": "", "res": "", "status": ""}
        row = {"display_name": name, "base_type": name, "row_kind": line["kind"], **{key: audit.Var(value) for key, value in values.items()}}
        if line["kind"] == "discount":
            row["discount_choice"] = audit.Var("自定义")
            row["discount_custom"] = audit.Var(line["percent"])
        else:
            config[name] = {key: line[key] for key in ("sale", "cost", "k", "single")}
        obj.calc_rows.append(row)
    obj.get_settings_snapshot = lambda: (config, [])
    obj.calculate(notify=False)
    return {
        "displayed_line_income": [row["res"].get() for row in obj.calc_rows],
        "displayed_totals": {key: getattr(obj, f"summary_{key}").get() for key in ("income", "cost", "profit", "margin")},
        "retained_records": len(obj.last_export_records),
        "errors": sum(issue["级别"] == "错误" for issue in obj.validation_issues),
        "warnings": sum(issue["级别"] != "错误" for issue in obj.validation_issues),
    }


def candidate(lines, blocked_reason):
    if blocked_reason:
        return {"status": "VALIDATION", "would_allow_commit_if_adopted": False, "reason": blocked_reason, "authoritative_totals": None}
    cent = Decimal("0.01")
    def money(value):
        amount = value.quantize(cent, rounding=ROUND_HALF_UP)
        return amount if amount else Decimal("0.00")
    with localcontext() as context:
        # All valid declared examples terminate exactly within this precision.
        # This is not the production expression/intermediate precision policy.
        context.prec = 64
        income, cost = Decimal(0), Decimal(0)
        amounts = []
        for line in lines:
            if line["kind"] == "discount":
                sale = money(income * (Decimal(line["percent"]) / 100 - 1))
                line_cost = Decimal("0.00")
            else:
                base = Decimal(line["q"])
                if not line["single"]:
                    base *= Decimal(line["h"]) * Decimal(line["w"])
                sale = money(base * Decimal(line["sale"]) * Decimal(line["k"] or "1"))
                line_cost = money(base * Decimal(line["cost"]))
            income += sale
            cost += line_cost
            amounts.append({"income": f"{sale:.2f}", "cost": f"{line_cost:.2f}", "profit": f"{sale - line_cost:.2f}"})
        profit = income - cost
        margin = None if not income else f"{(profit / income * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}%"
        return {"status": "candidate_only", "would_allow_commit_if_adopted": True, "lines": amounts, "totals": {"income": f"{income:.2f}", "cost": f"{cost:.2f}", "profit": f"{profit:.2f}", "margin": margin}}


def main():
    manifest = json.loads((ROOT / "docs/baseline/manifest.json").read_text(encoding="utf-8"))
    namespaces = {}
    sources = []
    for entry in manifest["files"]:
        inspected = audit.baseline.inspect_source(ROOT, entry)
        if inspected["status"] != "ok":
            raise SystemExit(f"Baseline changed: {entry['path']}; do not execute changed sources")
        sources.append({key: inspected[key] for key in ("role", "path", "normalized_git_blob_sha1", "normalized_sha256", "baseline_match_kind")})
        namespaces[entry["role"]] = runpy.run_path(str(ROOT / entry["path"]), run_name="p01_02_examples_only")
    results = []
    with tempfile.TemporaryDirectory(prefix="777-p01-02-") as temp:
        for case_id, title, lines, blocked_reason in CASES:
            results.append({"id": case_id, "title": title, "input": lines, "original": {role: original(ns, Path(temp), lines) for role, ns in namespaces.items()}, "recommended_candidate": candidate(lines, blocked_reason)})
    print(json.dumps({
        "task": "P01-02", "status": "proposal_examples_not_frozen", "source_commit": manifest["source_commit"],
        "environment": {"os": platform.system(), "python": platform.python_version(), "openpyxl": audit.openpyxl.__version__},
        "scope": "原calculate方法、控件替身、内存合成价格；候选Decimal示例；不启动GUI，不调用导出/截图/价格读取，不验证权限接口",
        "production_paths_accessed": False, "windows_acceptance": "not_performed_by_this_tool",
        "candidate_rejections": "E10-E13按待确认规则标记拒绝；并非已实现的验证器测试",
        "sources": sources, "cases": results,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
