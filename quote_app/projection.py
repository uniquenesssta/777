"""Frozen domain result -> legacy worksheet columns (no widget reads).

Financial amounts are exact two-decimal text cells. Excel's numeric cells cannot
represent the entire accepted integer-cent range. Historic readers already
accept numeric text; existing historic aggregation/editing is a P03 boundary.
"""
from decimal import Decimal

from quote_core import DiscountLine
from quote_core.numbers import exact_context, money_text
from quote_files.schema import RECORD_COLUMNS, DETAIL_HEADERS


def legacy_record(line):
    raw, price, amounts = line.raw, line.price, line.amounts
    fields = dict(line.normalized)
    discount = isinstance(raw, DiscountLine)
    margin = amounts.display()["margin"]
    # Numeric dimensions/prices retain canonical decimal text, not binary float.
    record = {
        "项目名称": raw.name, "基础类型": "折扣" if discount else raw.product_id,
        "是否单件": "折扣" if discount else "是" if price.single else "否",
        "高度(m)": fields.get("h"), "宽度(m)": fields.get("w"),
        "数量": fields.get("q"), "销售单价": fields.get("sale"),
        "成本单价": fields.get("cost"), "K系数": fields.get("k"),
        "折扣": fields["percent"] + "%" if discount else "—",
        "折扣系数": str(exact_context().multiply(Decimal(fields["percent"]), Decimal("0.01"))) if discount else None,
        "折前销售额": money_text(line.subtotal_before_cents) if discount else money_text(amounts.income_cents),
        "销售额": money_text(amounts.income_cents), "总成本": money_text(amounts.cost_cents),
        "利润": money_text(amounts.profit_cents), "利润率": margin or "—",
        "高度原文": "" if discount else raw.h, "宽度原文": "" if discount else raw.w,
        "数量原文": "" if discount else raw.q,
        "销售单价原文": "" if discount else price.sale,
        "成本单价原文": "" if discount else price.cost,
        "K系数原文": "" if discount else price.k,
    }
    return record


def append_quote(ws, timestamp, payload, *, kind_column, headers=None):
    details = payload.details
    prefix = dict(zip(DETAIL_HEADERS[:4], (timestamp, details.customer, details.order_ref, details.wechat)))
    mapping = headers or {key: i for i, key in enumerate(DETAIL_HEADERS, 1)}
    def append(record, kind):
        values = [None] * max(ws.max_column, max(mapping.values()), kind_column)
        for key, value in {**prefix, **record}.items():
            values[mapping[key] - 1] = value
        values[kind_column - 1] = kind
        ws.append(values)
    for line in payload.result.lines:
        append(legacy_record(line), line.raw.line_kind)
    totals = payload.result.totals.display()
    append({"项目名称": "--- 本次总计 ---", "销售额": totals["income"], "总成本": totals["cost"],
            "利润": totals["profit"], "利润率": totals["margin"] or "—"}, "order_total")
