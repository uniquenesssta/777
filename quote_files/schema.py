"""Versioned ledger layout recognition; no UI, file writes or formula evaluation."""
from dataclasses import dataclass

from .transactions import FileFailure

RECORD_COLUMNS = (
    "项目名称", "基础类型", "是否单件", "高度(m)", "宽度(m)", "数量",
    "销售单价", "成本单价", "K系数", "折扣", "折扣系数", "折前销售额",
    "销售额", "总成本", "利润", "利润率", "高度原文", "宽度原文", "数量原文",
    "销售单价原文", "成本单价原文", "K系数原文",
)
DETAIL_HEADERS = ("记录时间", "淘宝ID", "订单号", "微信号", *RECORD_COLUMNS)
IDENTITY_HEADERS = ("订单ID", "明细ID", "订单版本", "请求ID", "记录状态")
ALIASES = {"用户": "淘宝ID", "高度": "高度(m)", "宽度": "宽度(m)"}
KNOWN_SHEETS = {"利润明细", "输入问题", "价格设定", "备注", "订单备注", "订单价格快照", "_写入事务"}
PRICE_HISTORY_HEADERS = ("订单ID", "请求ID", "记录时间", "价格版本", "规则版本", "数值版本", "项目名称", "销售单价原文", "成本单价原文", "K系数原文", "是否单件")
APPENDIX_HEADERS = {
    "订单价格快照": (1, PRICE_HISTORY_HEADERS),
    "输入问题": (4, ("记录时间", "级别", "位置", "字段", "输入内容", "提示")),
    "价格设定": (4, ("项目名称", "销售单价原文", "成本单价原文", "K系数原文", "是否单件")),
    "订单备注": (1, ("请求ID", "订单ID", "备注")),
}


class UnsupportedSchema(FileFailure):
    pass


@dataclass(frozen=True)
class LedgerSchema:
    name: str
    header_row: int
    columns: dict
    tagged: bool
    identified: bool
    writable: bool
    readonly_reasons: tuple[str, ...]


def table_header(ws):
    if ws.max_column > 64 or ws.max_row > 100000:
        raise UnsupportedSchema("工作表超过当前100000行/64列读取范围，原件只读保留")
    for row in ws.iter_rows(max_row=min(ws.max_row, 40)):
        names = [(ALIASES.get(str(c.value).strip(), str(c.value).strip()), c.column)
                 for c in row if c.value is not None and str(c.value).strip()]
        if {"记录时间", "淘宝ID", "项目名称"}.issubset(dict(names)):
            if len({name for name, _ in names}) != len(names):
                raise UnsupportedSchema("明细表头重复或别名冲突，不能确定列映射")
            return row[0].row, dict(names)
    raise UnsupportedSchema("未识别到记录时间、淘宝ID/用户、项目名称表头")


def inspect_schema(book):
    if "利润明细" not in book.sheetnames:
        raise UnsupportedSchema("没有利润明细工作表，原件只读保留")
    ws = book["利润明细"]
    row, columns = table_header(ws)
    missing = set(DETAIL_HEADERS) - set(columns)
    unknown = set(columns) - {*DETAIL_HEADERS, "行类型", *IDENTITY_HEADERS, "备注"}
    if missing or unknown:
        raise UnsupportedSchema(f"明细字段不完整或未知：缺少{sorted(missing)}，未知{sorted(unknown)}")
    ids = set(IDENTITY_HEADERS) & set(columns)
    if ids and ids != set(IDENTITY_HEADERS):
        raise UnsupportedSchema("订单身份列不完整，原件只读保留")
    tagged = "行类型" in columns
    if ids and not tagged:
        raise UnsupportedSchema("订单身份存在但缺少明确行类型")
    reasons = []
    if not tagged and any(c.value is not None for cells in ws.iter_rows(min_row=row + 1) for c in cells):
        reasons.append("历史记录没有行类型，需显式转换新副本")
    if row != 6:
        reasons.append("明细表头不在第6行；不改写已有布局")
    unknown_sheets = set(book.sheetnames) - KNOWN_SHEETS
    if unknown_sheets:
        reasons.append("含未知工作表：" + "、".join(sorted(unknown_sheets)))
    for name, (header_row, expected) in APPENDIX_HEADERS.items():
        if name in book.sheetnames:
            sheet = book[name]
            if tuple(c.value for c in sheet[header_row]) != expected:
                reasons.append(name + "表格式未支持")
    for sheet in book.worksheets:
        if sheet.max_column > 64 or sheet.max_row > 100000:
            reasons.append(sheet.title + "超过读取范围")
            continue
        if any(c.data_type == "f" for cells in sheet.iter_rows() for c in cells):
            reasons.append(sheet.title + "含公式；只读取已有缓存，不保存公式工作簿")
        if getattr(sheet, "_images", None) or getattr(sheet, "_charts", None):
            reasons.append(sheet.title + "含未支持图形扩展")
    name = "identified-v1" if ids else "tagged-v1" if tagged else "legacy-26"
    if tuple(columns.get(key) for key in DETAIL_HEADERS) != tuple(range(1, 27)):
        name += "-mapped"
    return LedgerSchema(name, row, columns, tagged, bool(ids), not reasons, tuple(reasons))


def force_text(book):
    """Existing formulas are rejected before mutation; new user strings are text."""
    for ws in book.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if type(cell.value) is str:
                    cell.data_type = "s"


def create_template(ws, timestamp):
    if any(c.value is not None for row in ws.iter_rows() for c in row):
        raise FileFailure("已有工作表禁止模板重置，原件只读保留")
    ws.title = "利润明细"
    for row, values in enumerate((["六六派对利润明细"], ["最后导出时间", timestamp],
                   ["最近导出淘宝ID", "", "订单号", "", "微信号", ""],
                   ["总收入", "0.00", "总成本", "0.00", "总利润", "0.00", "综合利润率", "—"],
                   [], list(DETAIL_HEADERS)), 1):
        for col, value in enumerate(values, 1):
            ws.cell(row, col, value)
    return ws
