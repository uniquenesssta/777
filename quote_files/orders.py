"""Order projections and mutations, independent of Tk and file publication."""
from dataclasses import dataclass

from .schema import APPENDIX_HEADERS, INPUT_ORDER_HEADERS
from .transactions import FileFailure


@dataclass(frozen=True)
class OrderView:
    order_id: str
    revision: int
    state: str
    notes: tuple
    events: tuple
    inputs: tuple
    prices: tuple
    legacy_remark: str = ""


def related_rows(book, name):
    if name not in book.sheetnames:
        return ()
    row, expected = APPENDIX_HEADERS[name]
    sheet = book[name]
    header = tuple(c.value for c in sheet[row])
    if name == "输入问题":
        if header != INPUT_ORDER_HEADERS:
            return ()  # Old timestamp-only diagnostics have no proven owner.
    elif header != expected:
        return ()  # Unknown layouts are already read-only in schema inspection.
    return tuple(dict(zip(header, values)) for values in sheet.iter_rows(min_row=row + 1, values_only=True)
                 if any(v is not None for v in values))


def validate_associations(book, order_ids, log, operations):
    """Reject orphan/duplicate associations before any new publication."""
    seen = set()
    for name, operation in (("订单备注", "append_remark"), ("订单价格快照", "append_quote"), ("输入问题", "append_quote")):
        for row in related_rows(book, name):
            oid, rid = row.get("订单ID"), row.get("请求ID")
            if name == "输入问题" and oid is None and rid is None:
                continue  # Preserve older rows when the header is extended.
            if oid not in order_ids or rid not in log or log[rid]["order_id"] != oid or operations.get(rid) != operation:
                raise FileFailure(name + "没有匹配的订单/请求回执，原件只读保留")
            if name == "订单备注":
                if rid in seen or type(row["备注"]) is not str or not row["备注"].strip():
                    raise FileFailure("订单备注重复或内容无效，原件只读保留")
                seen.add(rid)


def order_views(book, schema):
    from .workbooks import receipts
    ws, h = book["利润明细"], schema.columns
    log = receipts(book)
    events = {}
    if log:
        for rid, operation, _, oid, _, timestamp, _ in book["_写入事务"].iter_rows(min_row=2, values_only=True):
            data = log[rid]
            events.setdefault(oid, []).append((rid, operation, timestamp, data.get("order_revision"), data.get("reason", "")))
    indexed = []
    for name in ("订单备注", "输入问题", "订单价格快照"):
        grouped = {}
        for data in related_rows(book, name):
            grouped.setdefault(data["订单ID"], []).append(data)
        indexed.append(grouped)
    notes, inputs, prices = indexed
    result = {}
    for row in range(schema.header_row + 1, ws.max_row + 1):
        oid = ws.cell(row, h["订单ID"]).value
        if not oid or ws.cell(row, h["行类型"]).value != "order_total":
            continue
        own_notes = tuple((r["请求ID"], r["备注"]) for r in notes.get(oid, ()))
        old = ws.cell(row, h["备注"]).value if "备注" in h and not own_notes else None
        result[oid] = OrderView(oid, ws.cell(row, h["订单版本"]).value,
            ws.cell(row, h["记录状态"]).value, own_notes, tuple(events.get(oid, ())),
            tuple(inputs.get(oid, ())), tuple(prices.get(oid, ())),
            str(old) if old is not None else "")
    return result


def edit_order(book, ws, headers, req, expected_revision, *, text=None, reason=None):
    from .workbooks import target_order
    operation = req.operation
    if operation not in {"append_remark", "void_order", "restore_order"}:
        raise FileFailure("未知订单操作，未写入")
    content = text if operation == "append_remark" else reason
    if type(content) is not str or not content.strip() or len(content.strip()) > 4096:
        raise FileFailure("请输入1至4096字符的" + ("追加备注" if operation == "append_remark" else "操作原因"))
    content = content.strip()
    rows = target_order(ws, headers, req.order_id, expected_revision)
    old_state = ws.cell(rows[0], headers["记录状态"]).value
    required = "void" if operation == "restore_order" else "active"
    if any(ws.cell(row, headers["记录状态"]).value != required for row in rows):
        raise FileFailure("恢复仅适用于作废订单" if required == "void" else "订单已作废；请先恢复后再操作")
    new_state = "active" if operation == "restore_order" else "void" if operation == "void_order" else "active"
    if operation == "append_remark":
        totals = [row for row in rows if ws.cell(row, headers["行类型"]).value == "order_total"]
        if len(totals) != 1:
            raise FileFailure("订单总计身份不完整，未写入")
        notes = book["订单备注"] if "订单备注" in book.sheetnames else book.create_sheet("订单备注")
        if notes.cell(1, 1).value is None:
            for col, name in enumerate(APPENDIX_HEADERS["订单备注"][1], 1):
                notes.cell(1, col, name)
        if tuple(c.value for c in notes[1]) != APPENDIX_HEADERS["订单备注"][1]:
            raise FileFailure("备注表格式不支持，未写入")
        notes.append([req.request_id, req.order_id, content])
        if "备注" not in headers:
            from .schema import table_header
            headers["备注"] = ws.max_column + 1
            ws.cell(table_header(ws)[0], headers["备注"], "备注")
        cell = ws.cell(totals[0], headers["备注"])
        cell.value = (str(cell.value) + "\n" if cell.value else "") + content
        cell.data_type = "s"
    for row in rows:
        ws.cell(row, headers["订单版本"], expected_revision + 1)
        ws.cell(row, headers["记录状态"], new_state)
    return {"order_revision": expected_revision + 1, "previous_state": old_state, "state": new_state,
            **({"note_text": content} if operation == "append_remark" else {"reason": content})}
