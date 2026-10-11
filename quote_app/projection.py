"""Frozen domain result -> legacy worksheet columns (no widget reads).

Financial amounts are exact two-decimal text cells. Excel's numeric cells cannot
represent the entire accepted integer-cent range. Historic readers already
accept numeric text; existing historic aggregation/editing is a P03 boundary.
"""
from decimal import Decimal

from quote_core import DiscountLine
from quote_core.numbers import exact_context, money_text


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


RECORD_COLUMNS = (
    "项目名称", "基础类型", "是否单件", "高度(m)", "宽度(m)", "数量",
    "销售单价", "成本单价", "K系数", "折扣", "折扣系数", "折前销售额",
    "销售额", "总成本", "利润", "利润率", "高度原文", "宽度原文", "数量原文",
    "销售单价原文", "成本单价原文", "K系数原文",
)


def append_quote(ws, timestamp, payload, *, kind_column):
    details = payload.details
    prefix = [timestamp, details.customer, details.order_ref, details.wechat]
    for line in payload.result.lines:
        record = legacy_record(line)
        ws.append(prefix + [record[key] for key in RECORD_COLUMNS])
        ws.cell(ws.max_row, kind_column, line.raw.line_kind)
    totals = payload.result.totals.display()
    ws.append(prefix + ["--- 本次总计 ---"] + [""] * 11 +
              [totals["income"], totals["cost"], totals["profit"], totals["margin"] or "—"])
    ws.cell(ws.max_row, kind_column, "order_total")
