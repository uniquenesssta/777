"""Typed ledger reads: ok/error/unsupported; no default-zero failures or writes."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import cached_property

from quote_core import Amounts
from quote_core.numbers import exact_context, scaled_decimal, settle
from .schema import UnsupportedSchema, inspect_schema
from .scheduling import checkpoint
from .transactions import digest, read_bytes
from .workbooks import open_book, validate_identity, receipts

TOTAL_NAME = "--- 本次总计 ---"
FINANCIAL = ("销售额", "总成本", "利润")


@dataclass(frozen=True)
class ReadIssue:
    code: str
    message: str
    cell: str = ""


@dataclass(frozen=True)
class LedgerRow:
    index: int
    kind: str
    state: str
    values: tuple[Decimal, Decimal, Decimal]


@dataclass
class LedgerRead:
    status: str
    totals: Amounts | None = None
    schema: object = None
    issues: tuple[ReadIssue, ...] = ()
    rows: tuple[LedgerRow, ...] = ()
    group_keys: dict = field(default_factory=dict)
    group_totals: dict = field(default_factory=dict)
    source_sha256: str | None = None
    summary_source: str | None = None
    remark: str = ""
    _detail_count: int | None = field(default=None, repr=False)

    @property
    def detail_count(self):
        return len(self.visible_rows) if self._detail_count is None else self._detail_count

    @cached_property
    def visible_rows(self):
        return frozenset(r.index for r in self.rows if r.kind in {"normal", "discount"} and r.state != "void")

    def __getitem__(self, key):
        # Transitional callers retain exact numeric access; failed reads raise.
        if self.status != "ok" or self.totals is None:
            raise ValueError("读取未成功：" + "; ".join(i.message for i in self.issues))
        return scaled_decimal(getattr(self.totals, key + "_cents"), 2)


class InvalidLedger(ValueError):
    def __init__(self, code, message, cell=""):
        super().__init__(message)
        self.issue = ReadIssue(code, message, cell)


def number(cell, cached, issues):
    value = cell.value
    if cell.data_type == "f":
        value = cached[cell.coordinate].value if cached is not None else None
        if value is None:
            raise InvalidLedger("FORMULA_WITHOUT_CACHE", "公式没有可读缓存，未执行公式", cell.coordinate)
        issues.append(ReadIssue("FORMULA_CACHE_USED", "只读取已有公式缓存，未验证缓存时效", cell.coordinate))
    if type(value) not in (str, int, float, Decimal) or len(str(value)) > 256:
        raise InvalidLedger("INVALID_AMOUNT", "金额缺失、类型无效或过长", cell.coordinate)
    try:
        result = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise InvalidLedger("INVALID_AMOUNT", "金额不是十进制数值", cell.coordinate) from exc
    if not result.is_finite() or abs(result.as_tuple().exponent) > 60 or result.copy_abs() > Decimal("1000000000000000000"):
        raise InvalidLedger("INVALID_AMOUNT", "金额非有限值或超出范围", cell.coordinate)
    return result


def amount_values(ws, cached, index, columns, issues):
    values = tuple(number(ws.cell(index, columns[key]), cached, issues) for key in FINANCIAL)
    expected = settle(exact_context().subtract(values[0], values[1]))
    if expected != settle(values[2]):
        raise InvalidLedger("AMOUNT_MISMATCH", "收入、成本与利润不一致", str(index))
    return values


def analyze(book, cached_book=None):
    schema = None
    issues = []
    try:
        schema = inspect_schema(book)
        ws, h = book["利润明细"], schema.columns
        cached = cached_book["利润明细"] if cached_book is not None else None
        issues.extend(ReadIssue("READ_ONLY", reason) for reason in schema.readonly_reasons)
        rows, prefixes = [], {}
        for index, cells in enumerate(ws.iter_rows(min_row=schema.header_row + 1), schema.header_row + 1):
            checkpoint()
            if all(c.value is None for c in cells):
                continue
            value = lambda key: cells[h[key] - 1].value
            if schema.tagged:
                kind = value("行类型")
                if kind not in {"normal", "discount", "order_total"}:
                    raise InvalidLedger("UNKNOWN_ROW_KIND", "行类型缺失或未知", str(index))
            else:
                name = value("项目名称")
                marker = name == TOTAL_NAME or (cells[0].value == TOTAL_NAME and name is None)
                if marker:
                    # Exact legacy footer shape, never a generic name-prefix guess.
                    nonmoney = ("基础类型", "是否单件", "数量", "销售单价", "成本单价", "K系数")
                    if any(value(key) not in (None, "") for key in nonmoney):
                        raise InvalidLedger("AMBIGUOUS_ROW_KIND", "历史总计名称与商品字段冲突", str(index))
                    kind = "order_total"
                elif name in (None, "", "备注", "文件备注") or str(name).startswith("---"):
                    raise InvalidLedger("AMBIGUOUS_ROW_KIND", "历史行类型不明确，原件只读保留", str(index))
                else:
                    kind = "normal"
            state = value("记录状态") if "记录状态" in h else "active"
            if state not in {"active", "void", None}:
                raise InvalidLedger("INVALID_RECORD_STATE", "未知记录状态", str(index))
            values = amount_values(ws, cached, index, h, issues)
            rows.append(LedgerRow(index, kind, state or "active", values))
            prefixes[index] = tuple(str(value(key) if value(key) is not None else "") for key in ("淘宝ID", "记录时间", "订单号", "微信号"))
        validate_identity(ws, schema.header_row, h)
        if schema.identified:
            log = receipts(book)
            operations = {r[0]: r[1] for r in book["_写入事务"].iter_rows(min_row=2, values_only=True)} if log else {}
            for r in rows:
                checkpoint()
                oid = ws.cell(r.index, h["订单ID"]).value
                rid = ws.cell(r.index, h["请求ID"]).value
                if oid and (rid not in log or log[rid]["order_id"] != oid or operations[rid] != "append_quote"):
                    raise InvalidLedger("MISSING_RECEIPT", "订单没有匹配的原始追加回执", str(r.index))
            from .orders import validate_associations
            validate_associations(book, {ws.cell(r.index, h["订单ID"]).value for r in rows}, log, operations)
        keys, totals = groups(ws, h, rows, prefixes, issues)
        if rows and all(r.kind == "order_total" for r in rows):
            raise InvalidLedger("ORPHAN_ORDER_TOTAL", "仅有总计行而没有可核对明细，不作为零金额文件")
        context = exact_context()
        detail = [r for r in rows if r.kind != "order_total" and r.state != "void"]
        values = [Decimal(0), Decimal(0), Decimal(0)]
        for row in detail:
            checkpoint()
            values = [context.add(total, value) for total, value in zip(values, row.values)]
        summary = {}
        labels = {"总收入": "income", "总成本": "cost", "总利润": "profit"}
        preamble = ws.iter_rows(max_row=schema.header_row - 1) if schema.header_row > 1 else ()
        for cells in preamble:
            for cell in cells:
                if cell.value in labels:
                    key = labels[cell.value]
                    if key in summary:
                        raise InvalidLedger("DUPLICATE_SUMMARY", "摘要字段重复", cell.coordinate)
                    summary[key] = number(ws.cell(cell.row, cell.column + 1), cached, issues)
        source = "details"
        if summary:
            if set(summary) != {"income", "cost", "profit"}:
                raise InvalidLedger("INCOMPLETE_SUMMARY", "已有摘要字段不完整，不使用零值兜底")
            summary_values = [summary[k] for k in ("income", "cost", "profit")]
            if tuple(map(settle, summary_values)) != tuple(map(settle, values)):
                raise InvalidLedger("SUMMARY_MISMATCH", "已有摘要与有效明细不一致，未静默替换摘要")
            values, source = summary_values, "header"
        amounts = Amounts(settle(values[0]), settle(values[1]))
        if amounts.profit_cents != settle(values[2]):
            raise InvalidLedger("TOTAL_MISMATCH", "明细汇总利润不一致")
        remark = ""
        if "备注" in h:
            notes = [ws.cell(r.index, h["备注"]).value for r in rows]
            remark = next((str(v) for v in reversed(notes) if v is not None), "")
        if "备注" in book.sheetnames:
            sheet = book["备注"]
            note = sheet["B5"].value or sheet["B4"].value
            if note is not None:
                remark = str(note)
                issues.append(ReadIssue("LEGACY_FILE_REMARK", "文件备注归属未知，仅作为文件说明"))
        return LedgerRead("ok", amounts, schema, tuple(issues), tuple(rows), keys, totals, summary_source=source, remark=remark)
    except UnsupportedSchema as exc:
        return LedgerRead("unsupported", schema=schema, issues=(ReadIssue("UNSUPPORTED_SCHEMA", str(exc)),))
    except InvalidLedger as exc:
        return LedgerRead("error", schema=schema, issues=tuple(issues) + (exc.issue,))
    except Exception as exc:
        return LedgerRead("error", schema=schema, issues=tuple(issues) + (ReadIssue("READ_ERROR", f"{type(exc).__name__}: {exc}"),))


def groups(ws, headers, rows, prefixes, issues):
    keys, totals, pending = {}, {}, []
    context = exact_context()
    def put(indices, key):
        value = Decimal(0)
        for r in indices:
            checkpoint()
            keys[r.index] = key
            if r.state != "void" and r.kind != "order_total":
                value = context.add(value, r.values[0])
        if any(r.state != "void" and r.kind != "order_total" for r in indices):
            totals[key] = scaled_decimal(settle(value), 2)
    def flush():
        candidates = {}
        for r in pending:
            checkpoint()
            candidates.setdefault(prefixes[r.index], []).append(r)
        for prefix, same in candidates.items():
            checkpoint()
            if len(same) == 1 and all(prefix[:3]):
                put(same, ("legacy", same[0].index))
            else:
                issues.append(ReadIssue("AMBIGUOUS_LEGACY_GROUP", "历史订单缺少稳定编号或明确边界，未合并总销售额", str(same[0].index)))
                for r in same:
                    checkpoint()
                    keys[r.index] = ("ambiguous", r.index)
        pending.clear()
    identified = {}
    for r in rows:
        checkpoint()
        oid = ws.cell(r.index, headers["订单ID"]).value if "订单ID" in headers else None
        if oid:
            flush()
            identified.setdefault(oid, []).append(r)
        elif r.kind == "order_total":
            if pending and len({prefixes[x.index] for x in pending}) == 1 and prefixes[r.index] == prefixes[pending[0].index]:
                subtotal = [Decimal(0)] * 3
                for x in pending:
                    checkpoint()
                    subtotal = [context.add(a, b) for a, b in zip(subtotal, x.values)]
                if tuple(map(settle, subtotal)) != tuple(map(settle, r.values)):
                    raise InvalidLedger("ORDER_TOTAL_MISMATCH", "历史订单总计与明细不符", str(r.index))
                put(pending, ("legacy_block", pending[0].index))
                pending.clear()
            else:
                issues.append(ReadIssue("UNBOUND_LEGACY_TOTAL", "历史总计缺少可核对的订单边界，仅按有效明细汇总", str(r.index)))
                flush()
        else:
            pending.append(r)
    flush()
    for oid, group in identified.items():
        checkpoint()
        put(group, ("order", oid))
        detail = [r for r in group if r.kind != "order_total"]
        footer = [r for r in group if r.kind == "order_total"][0]
        sums = [Decimal(0)] * 3
        for r in detail:
            checkpoint()
            sums = [context.add(a, b) for a, b in zip(sums, r.values)]
        if tuple(map(settle, sums)) != tuple(map(settle, footer.values)):
            raise InvalidLedger("ORDER_TOTAL_MISMATCH", "订单总计与明细不符", str(footer.index))
    return keys, totals


def analyze_raw(raw):
    from .documents import parse_document
    return parse_document(raw, opener=open_book, analyzer=analyze).ledger()


def read_document(path):
    from .documents import failed_document, parse_document
    try:
        return parse_document(read_bytes(path), opener=open_book, analyzer=analyze)
    except Exception as exc:
        return failed_document(exc)


def read_ledger(path):
    return read_document(path).ledger()
