# -*- coding: utf-8 -*-
"""
六六派对报价 / 利润计算器 - 局域网子版本

本版重点：
1. 保留计算主页、淘宝ID、订单号、微信号、折扣行、Excel 导出和 Excel 记录查看。
2. 删除利润分析页和价格设定页；子版本不能查看成本、利润、利润率，也不能修改价格设定。
3. 在Excel记录页保存本机数据连接；价格与输出目录从母版storage.json继承。
4. 首次连接须显式选择，旧版路径仅作导入建议；读取失败只保留草稿，禁止正式输出。
5. Excel 和截图目录自动继承母版 config.json；子版显示只读目录，不可更改。
6. Excel 记录页只读，仅显示销售相关字段。
7. 子版本与母版本共用同一天 Excel 文件；可追加导出，并读取母版本更新/删除后的同一文件。

依赖：
- tkinter：Python 标准库自带
- openpyxl：用于导出/读取 Excel，安装命令：pip install openpyxl
- pillow：用于截图，安装命令：pip install pillow
"""

import os
import sys
import re
import time
import tkinter as tk
from quote_app import QuoteApplicationMixin, BackgroundApplicationMixin
from quote_app.connections import default_settings_file
from tkinter import filedialog, messagebox, ttk

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    Workbook = None
    load_workbook = None


# ======================== 旧版目录导入建议（不自动访问） ========================
# Excel 每天共用一个文件，统一保存到：\\192.168.4.38\14T共享盘\葛宁\PyInstaller\利润表
# 价格设定 JSON 统一读取母版本：\\192.168.4.38\14T共享盘\葛宁\PyInstaller\config.json
APP_SAVE_ROOT = r"\\192.168.4.38\14T共享盘\葛宁\PyInstaller"
LAN_DATA_DIR = os.path.join(APP_SAVE_ROOT, "利润表")
LAN_PRICE_CONFIG_FILE = os.path.join(APP_SAVE_ROOT, "config.json")
LAN_SCREENSHOT_DIR = os.path.join(APP_SAVE_ROOT, "截图")  # 截图会按天保存到该目录下的 YYYYMMDD 子文件夹
DAILY_EXCEL_PREFIX = "利润明细"

# 程序图标路径。支持 .ico 或 .png。
# 建议封包时把图标文件放在 .py 同目录，例如：APP_ICON_PATH = r"app.ico"
# 如果填写绝对路径，也可以直接使用，例如：APP_ICON_PATH = r"E:\\图标\\app.ico"
# PyInstaller 封包时需要同时使用 --icon 和 --add-data，具体命令见下方说明。
APP_ICON_PATH = r"app.ico"

# 历史单件策略：仅为旧三元JSON识别单件项目，不作为价格兜底。
DEFAULT_PRICE_ITEMS = [
    {"name": "背景板", "sale": "11.5", "cost": "5.0", "k": "1.0", "single": False},
    {"name": "喷绘", "sale": "15.0", "cost": "7.0", "k": "1.0", "single": False},
    {"name": "KT板", "sale": "12.5", "cost": "11.5", "k": "2.2", "single": False},
    {"name": "支架", "sale": "50.0", "cost": "20.0", "k": "1.0", "single": True},
    {"name": "设计费", "sale": "100.0", "cost": "0.0", "k": "1.0", "single": True},
    {"name": "配套气球", "sale": "30.0", "cost": "15.0", "k": "1.0", "single": True},
    {"name": "其他", "sale": "1.0", "cost": "1.0", "k": "1.0", "single": False},
]
# ===============================================================


def get_resource_path(path_text):
    """兼容开发环境和 PyInstaller 封包后的资源路径。

    APP_ICON_PATH 如果填写相对路径，例如 app.ico：
    - 开发运行时：优先从 .py 同目录读取；
    - PyInstaller onefile/onedir：优先从打包资源目录读取；
    - 如果图标放在 exe 同目录，也会尝试读取。
    """
    path = str(path_text or "").strip().strip('"').strip("'")
    if not path:
        return ""
    if os.path.isabs(path):
        return path

    candidates = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, path))
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(os.path.dirname(sys.executable), path))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), path))
    candidates.append(os.path.abspath(path))

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return candidates[0] if candidates else path


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner.bind(
            "<Configure>",
            lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )

        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _on_mousewheel(self, event):
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
            if widget is not None and str(widget).startswith(str(self)):
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass


class TableRowHandle:
    """计算列表表格行句柄。

    表头和所有数据行都直接放在同一个 grid 父容器里，
    普通项目行、折扣行、表头会共享同一组列宽，避免列线错位。
    """

    def __init__(self, parent, row_index):
        self.parent = parent
        self.row_index = row_index
        self.cells = []

    def add_cell(self, cell):
        self.cells.append(cell)

    def destroy(self):
        for cell in list(self.cells):
            try:
                cell.destroy()
            except Exception:
                pass
        self.cells = []
        try:
            self.parent.grid_rowconfigure(self.row_index, minsize=0)
        except Exception:
            pass


class PriceCalculator(BackgroundApplicationMixin, QuoteApplicationMixin):
    local_settings_file = default_settings_file('sales')
    legacy_data_root = APP_SAVE_ROOT
    quote_role = "sales"
    SPECIAL_DISCOUNT_TYPE = "折扣"
    DISCOUNT_CHOICES = ["95%", "90%", "85%", "80%", "75%", "70%", "50%", "自定义"]
    CALC_COLUMNS = [
        # 标题、最小像素宽、扩展权重。所有列在同一个 grid 中统一分配宽度。
        ("项目名称", 250, 3),
        ("高(m)", 110, 1),
        ("宽(m)", 110, 1),
        ("数量", 90, 1),
        ("折扣/说明", 180, 2),
        ("销售额小计", 130, 1),
        ("状态", 95, 1),
        ("操作", 90, 1),
    ]

    def __init__(self, root):
        self.root = root
        self.root.title("六六派对报价 / 利润计算器 - 子版本")
        self.apply_window_icon()
        self.root.geometry("1180x840")
        self.root.minsize(1040, 720)

        self.config_file = "config.json"  # 仅用于兼容旧方法；子版本不再写入本机价格设定。
        self.default_report_dir = ""
        self.report_dir = self.default_report_dir
        self.price_config_file = ""
        self.image_dir = ""
        # Storage is resolved from the shared config before any directory I/O.

        self.default_items = [dict(item) for item in DEFAULT_PRICE_ITEMS]
        self.price_source_text = ""

        self.setting_rows = []
        self.calc_rows = []
        self.calc_table_next_row = 1
        self.last_export_records = []
        self.validation_issues = []
        self.last_config_snapshot = {}
        self.current_excel_path = None
        self.excel_view_row_map = {}

        self.user_name = tk.StringVar(value="默认淘宝ID")  # 兼容旧代码命名：这里实际表示“淘宝ID”
        self.order_no = tk.StringVar(value="")
        self.wechat_no = tk.StringVar(value="")
        self.feedback_var = tk.StringVar(value="")
        self.price_source_var = tk.StringVar(value=self.price_source_text)
        self.issue_summary_var = tk.StringVar(value="暂无输入问题。")
        self.total_val = tk.StringVar(value="总计：0.00 元")
        self.summary_income = tk.StringVar(value="0.00")
        self.summary_cost = tk.StringVar(value="0.00")
        self.summary_profit = tk.StringVar(value="0.00")
        self.summary_margin = tk.StringVar(value="0%")
        self.excel_selected_file = tk.StringVar(value="未选择 Excel 文件")
        self.excel_sheet_var = tk.StringVar(value="")
        self.export_dir_var = tk.StringVar(value=self.report_dir)

        self.initialize_background_io()
        self.initialize_quote_state()
        self._build_style()
        self._build_layout()
        self.load_settings_to_ui()
        self.refresh_item_selector()

        self.install_quote_controls()
        self.install_background_controls()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- 基础工具 ----------

    def apply_window_icon(self):
        """设置窗口左上角图标。

        这里不弹窗提示，图标路径为空或文件不存在时自动跳过，
        避免员工端看到内部路径或报错。
        """
        icon_path = get_resource_path(APP_ICON_PATH)
        if not icon_path or not os.path.exists(icon_path):
            return

        try:
            ext = os.path.splitext(icon_path)[1].lower()
            if ext == ".ico" and os.name == "nt":
                self.root.iconbitmap(default=icon_path)
            else:
                self._app_icon_image = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, self._app_icon_image)
        except Exception:
            # 图标不影响主程序使用，失败时静默跳过。
            pass

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Title.TLabel", font=("Arial", 15, "bold"))
        style.configure("Section.TLabelframe.Label", font=("Arial", 10, "bold"))
        style.configure("Feedback.TLabel", font=("Arial", 10))
        style.configure("Total.TLabel", font=("Arial", 14, "bold"))
        style.configure("Accent.TButton", font=("Arial", 10, "bold"))

    def get_default_report_dir(self):
        return self.report_dir

    def get_price_config_file(self):
        return self.config_file

    def get_screenshot_dir(self):
        return self.image_dir

    def normalize_path_text(self, text, fallback=None):
        path = str(text or "").strip().strip('"').strip("'")
        path = os.path.expandvars(os.path.expanduser(path))
        if path:
            return path
        if fallback is not None:
            return fallback
        return getattr(self, "default_report_dir", "利润表")

    def ensure_directories(self):
        if self._io_enabled():
            return BackgroundApplicationMixin.ensure_directories(self)
        for folder in [self.report_dir, self.image_dir]:
            if not folder:
                continue
            if not os.path.exists(folder):
                os.makedirs(folder, exist_ok=True)

    def format_display(self, value):
        return f"{round(float(value), 2):.2f}"

    def clean_filename(self, text):
        return re.sub(r"[\\/:*?\"<>|]", "_", str(text).strip() or "默认淘宝ID")

    def set_feedback(self, text, is_error=False):
        self.feedback_var.set(text)
        if hasattr(self, "feedback_label"):
            self.feedback_label.configure(foreground="#c0392b" if is_error else "#2c3e50")

    def add_issue(self, issues, level, location, field, raw_value, message):
        issues.append(
            {
                "级别": level,
                "位置": location,
                "字段": field,
                "输入内容": str(raw_value),
                "提示": message,
            }
        )


    # ---------- 界面 ----------

    def _build_layout(self):
        top = ttk.Frame(self.root, padding=(14, 10, 14, 6))
        top.pack(fill=tk.X)

        ttk.Label(top, text="六六派对报价 / 利润计算器", style="Title.TLabel").pack(side=tk.LEFT)

        user_box = ttk.Frame(top)
        user_box.pack(side=tk.RIGHT)
        ttk.Label(user_box, text="淘宝ID：").grid(row=0, column=0, sticky=tk.E, padx=(0, 4))
        ttk.Entry(user_box, textvariable=self.user_name, width=14).grid(row=0, column=1, sticky=tk.W, padx=(0, 8))
        ttk.Label(user_box, text="订单号：").grid(row=0, column=2, sticky=tk.E, padx=(0, 4))
        ttk.Entry(user_box, textvariable=self.order_no, width=15).grid(row=0, column=3, sticky=tk.W, padx=(0, 8))
        ttk.Label(user_box, text="微信号：").grid(row=0, column=4, sticky=tk.E, padx=(0, 4))
        ttk.Entry(user_box, textvariable=self.wechat_no, width=14).grid(row=0, column=5, sticky=tk.W)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))

        self.calc_page = ttk.Frame(self.notebook)
        self.feedback_page = ttk.Frame(self.notebook)
        self.excel_page = ttk.Frame(self.notebook)

        self.notebook.add(self.calc_page, text=" 计算主页 ")
        self.notebook.add(self.feedback_page, text=" 输入反馈 ")
        self.notebook.add(self.excel_page, text=" Excel记录 ")

        self.setup_calc_page()
        self.setup_feedback_page()
        self.setup_excel_page()

    def setup_calc_page(self):
        add_frame = ttk.LabelFrame(self.calc_page, text="添加项目", padding=10, style="Section.TLabelframe")
        add_frame.pack(fill=tk.X, padx=10, pady=(10, 6))

        ttk.Label(add_frame, text="品名备注：").grid(row=0, column=0, sticky=tk.W, padx=(0, 6))
        self.custom_item_entry = ttk.Entry(add_frame, width=22)
        self.custom_item_entry.grid(row=0, column=1, sticky=tk.W, padx=(0, 14))

        ttk.Label(add_frame, text="项目类型：").grid(row=0, column=2, sticky=tk.W, padx=(0, 6))
        self.item_selector = ttk.Combobox(add_frame, width=24, state="readonly")
        self.item_selector.grid(row=0, column=3, sticky=tk.W, padx=(0, 14))

        ttk.Button(add_frame, text="+ 添加到列表", command=self.handle_add_item, style="Accent.TButton").grid(row=0, column=4, sticky=tk.W)
        ttk.Button(add_frame, text="刷新价格设定", command=lambda: self.reload_price_settings_from_json(silent=True)).grid(row=0, column=5, sticky=tk.W, padx=(8, 0))
        # 子版本隐藏价格来源和兜底说明，避免员工端显示内部路径/配置提示。

        list_frame = ttk.LabelFrame(self.calc_page, text="计算列表", padding=8, style="Section.TLabelframe")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        self.calc_scroll = ScrollableFrame(list_frame)
        self.calc_scroll.pack(fill=tk.BOTH, expand=True)
        self.calc_table_next_row = 1
        self.build_calc_header(self.calc_scroll.inner)

        bottom = ttk.Frame(self.calc_page, padding=(10, 4, 10, 10))
        bottom.pack(fill=tk.X)

        buttons = ttk.Frame(bottom)
        buttons.pack(side=tk.LEFT)
        ttk.Button(buttons, text="开始计算", command=self.calculate, style="Accent.TButton").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text="查看输入反馈", command=self.go_to_feedback_page).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text="清空所有行", command=self.reset).pack(side=tk.LEFT, padx=6)
        self.calc_export_button = ttk.Button(buttons, text="导出 Excel", command=self.export_to_excel)
        self.calc_export_button.pack(side=tk.LEFT, padx=6)
        self.calc_screenshot_button = ttk.Button(buttons, text="保存窗口截图", command=self.save_screenshot)
        self.calc_screenshot_button.pack(side=tk.LEFT, padx=6)
        self.calc_quote_image_button = ttk.Button(buttons, text="保存完整报价图", command=self.save_quote_image)
        self.calc_quote_image_button.pack(side=tk.LEFT, padx=6)
        ttk.Label(self.calc_page, text="窗口截图仅保存当前可见内容，遮挡可能影响；保存全部明细请使用完整报价图。", foreground="#7f8c8d").pack(anchor=tk.W, padx=6, pady=(2, 0))

        ttk.Label(bottom, textvariable=self.total_val, style="Total.TLabel", foreground="#2c3e50").pack(side=tk.RIGHT)

        # 已隐藏计算主页底部说明栏；输入问题请进入“输入反馈”页面查看。

    def setup_feedback_page(self):
        container = ttk.Frame(self.feedback_page, padding=14)
        container.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(container)
        top.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(top, text="输入校验反馈", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Button(top, text="返回计算主页", command=lambda: self.notebook.select(self.calc_page)).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(top, text="重新计算", command=self.calculate).pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Label(
            container,
            text="这里集中显示计算时发现的问题。出现“错误”时，相关行不会进入利润明细和 Excel 明细；“提醒”表示系统仍会计算，但建议人工确认。",
            foreground="#7f8c8d",
            wraplength=1080,
        ).pack(fill=tk.X, pady=(0, 8))

        summary_box = ttk.LabelFrame(container, text="反馈概览", padding=10, style="Section.TLabelframe")
        summary_box.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(summary_box, textvariable=self.issue_summary_var, font=("Arial", 11, "bold"), foreground="#2c3e50").pack(anchor=tk.W)

        tree_frame = ttk.Frame(container)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        issue_columns = ("level", "location", "field", "value", "message")
        self.issue_tree = ttk.Treeview(tree_frame, columns=issue_columns, show="headings", height=18)
        issue_headings = {
            "level": "级别",
            "location": "位置",
            "field": "字段",
            "value": "输入内容",
            "message": "提示",
        }
        issue_widths = {"level": 80, "location": 190, "field": 140, "value": 240, "message": 540}
        for col in issue_columns:
            self.issue_tree.heading(col, text=issue_headings[col])
            self.issue_tree.column(col, width=issue_widths[col], anchor=tk.W)

        y_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.issue_tree.yview)
        x_scroll = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.issue_tree.xview)
        self.issue_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.issue_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self.issue_tree.tag_configure("错误", foreground="#c0392b")
        self.issue_tree.tag_configure("提醒", foreground="#8e44ad")

    def get_calc_column(self, col_index):
        column = self.CALC_COLUMNS[col_index]
        if len(column) == 2:
            title, width = column
            weight = 1
        else:
            title, width, weight = column
        return title, width, weight

    def build_calc_header(self, parent):
        """表头和数据行共用同一个 grid 父容器，确保列线严格对齐。"""
        for col_index, _column in enumerate(self.CALC_COLUMNS):
            title, width, weight = self.get_calc_column(col_index)
            parent.grid_columnconfigure(col_index, minsize=width, weight=weight, uniform="calc_table")
            cell = tk.Frame(parent, height=32, bd=1, relief="groove", bg="#eef3f7")
            cell.grid(row=0, column=col_index, sticky="nsew", padx=0, pady=(0, 2))
            cell.grid_propagate(False)
            label = tk.Label(cell, text=title, bg="#eef3f7", fg="#2c3e50", font=("Arial", 10, "bold"))
            label.pack(fill=tk.BOTH, expand=True)
        parent.grid_rowconfigure(0, minsize=32)

    def create_calc_row_frame(self, kind="normal"):
        bg = "#ffffff" if kind == "normal" else "#fffaf2"
        row_handle = TableRowHandle(self.calc_scroll.inner, self.calc_table_next_row)
        self.calc_table_next_row += 1
        self.calc_scroll.inner.grid_rowconfigure(row_handle.row_index, minsize=44)
        return row_handle, bg

    def create_calc_cell(self, frame, col_index, bg="#ffffff"):
        _title, _width, _weight = self.get_calc_column(col_index)
        # 直接把每一个单元格 grid 到 calc_scroll.inner，所有行共享一套列宽。
        cell = tk.Frame(self.calc_scroll.inner, height=42, bd=1, relief="sunken", bg=bg)
        cell.grid(row=frame.row_index, column=col_index, sticky="nsew", padx=0, pady=1)
        cell.grid_propagate(False)
        frame.add_cell(cell)
        return cell

    def pack_in_cell(self, parent, widget, padx=6, pady=5):
        widget.pack(fill=tk.BOTH, expand=True, padx=padx, pady=pady)
        return widget

    def go_to_feedback_page(self):
        if hasattr(self, "feedback_page"):
            self.notebook.select(self.feedback_page)

    def notify_validation_errors(self, error_count, warn_count):
        self.go_to_feedback_page()
        messagebox.showwarning(
            "发现输入错误",
            f"本次计算发现 {error_count} 个错误、{warn_count} 个提醒。\n\n"
            "已切换到“输入反馈”页面，请根据提示修改后重新计算。",
        )

    # ---------- 设置数据 ----------


    def clear_setting_rows(self):
        for row in list(self.setting_rows):
            frame = row.get("frame")
            if frame is not None:
                try:
                    frame.destroy()
                except Exception:
                    pass
        self.setting_rows = []


    def add_setting_row(self, name="", sale="", cost="", k="", single=False):
        # 子版本删除了“价格设定”页面，但计算仍然需要项目价格数据。
        # 因此这里可以创建“无界面”的设置行；若以后恢复设置页，也兼容原来的界面行。
        name_var = tk.StringVar(value=name)
        sale_var = tk.StringVar(value=sale)
        cost_var = tk.StringVar(value=cost)
        k_var = tk.StringVar(value=k)
        single_var = tk.BooleanVar(value=single)

        frame = None
        if hasattr(self, "settings_scroll"):
            frame = ttk.Frame(self.settings_scroll.inner)
            frame.pack(fill=tk.X, pady=3)
            ttk.Entry(frame, textvariable=name_var, width=24).pack(side=tk.LEFT, padx=4)
            ttk.Entry(frame, textvariable=sale_var, width=18).pack(side=tk.LEFT, padx=4)
            ttk.Entry(frame, textvariable=cost_var, width=18).pack(side=tk.LEFT, padx=4)
            ttk.Entry(frame, textvariable=k_var, width=14).pack(side=tk.LEFT, padx=4)
            ttk.Checkbutton(frame, variable=single_var).pack(side=tk.LEFT, padx=(28, 26))
            ttk.Button(frame, text="删除", width=6, command=lambda: self.remove_setting_row(frame)).pack(side=tk.LEFT, padx=4)

        row = {
            "frame": frame,
            "name": name_var,
            "sale": sale_var,
            "cost": cost_var,
            "k": k_var,
            "single": single_var,
        }
        self.setting_rows.append(row)
        self.watch_quote_row(row, settings=True)

    def update_discount_editor_state(self, row):
        choice = row["discount_choice"].get()
        if choice == "自定义":
            row["custom_entry"].configure(state="normal")
            if not row["discount_custom"].get().strip():
                row["discount_custom"].set("90")
        else:
            row["custom_entry"].configure(state="disabled")

    def remove_setting_row(self, frame):
        for idx, row in enumerate(self.setting_rows):
            if row["frame"] == frame:
                if row.get("frame") is not None:
                    row["frame"].destroy()
                self.setting_rows.pop(idx)
                self.quote_input_changed()
                break
        self.refresh_item_selector()


    def refresh_item_selector(self):
        config, _issues = self.get_settings_snapshot()
        values = list(config.keys()) + [self.SPECIAL_DISCOUNT_TYPE]
        self.item_selector.configure(values=values)
        current = self.item_selector.get().strip()
        if values and current not in values:
            self.item_selector.set(values[0])
        elif not values:
            self.item_selector.set("")


    # ---------- 计算主页 ----------

    def handle_add_item(self):
        config, issues = self.get_settings_snapshot()
        self.refresh_item_selector()
        base_type = self.item_selector.get().strip()
        prefix = self.custom_item_entry.get().strip()

        if base_type == self.SPECIAL_DISCOUNT_TYPE:
            display_name = f"{prefix}（折扣）" if prefix else "整单折扣"
            self.add_discount_calc_row(display_name)
            self.custom_item_entry.delete(0, tk.END)
            self.render_issues(issues)
            self.set_feedback("已添加折扣行：折扣行按它前面的当前小计计算，建议放在需要折扣的项目后面。", is_error=False)
            return

        if not config:
            self.render_issues(issues)
            self.set_feedback("没有载入有效价格；请修复价格文件并点击刷新。", is_error=True)
            return

        if base_type not in config:
            self.add_issue(issues, "错误", "添加项目", "项目类型", base_type, "请选择一个有效的项目类型。")
            self.render_issues(issues)
            self.set_feedback("请选择一个有效的项目类型。", is_error=True)
            return

        display_name = f"{prefix}（{base_type}）" if prefix else base_type
        self.add_calc_row(display_name, base_type, config[base_type].get("single", False))
        self.custom_item_entry.delete(0, tk.END)

        if issues:
            self.render_issues(issues)
            self.set_feedback(f"项目已添加，但价格设定有 {len(issues)} 条提醒。", is_error=True)
        else:
            self.set_feedback(f"已添加：{display_name}", is_error=False)

    def add_calc_row(self, display_name, base_type, single=False):
        frame, bg = self.create_calc_row_frame("normal")

        h_var = tk.StringVar(value="" if single else "1.0")
        w_var = tk.StringVar(value="" if single else "1.0")
        q_var = tk.StringVar(value="1")
        note_var = tk.StringVar(value="—")
        result_var = tk.StringVar(value="0.00")
        status_var = tk.StringVar(value="未计算")

        name_cell = self.create_calc_cell(frame, 0, bg)
        tk.Label(name_cell, text=display_name, anchor="w", bg=bg, fg="#2c3e50").pack(fill=tk.BOTH, expand=True, padx=8)

        h_cell = self.create_calc_cell(frame, 1, bg)
        w_cell = self.create_calc_cell(frame, 2, bg)
        q_cell = self.create_calc_cell(frame, 3, bg)
        h_entry = ttk.Entry(h_cell, textvariable=h_var, justify="center")
        w_entry = ttk.Entry(w_cell, textvariable=w_var, justify="center")
        q_entry = ttk.Entry(q_cell, textvariable=q_var, justify="center")
        self.pack_in_cell(h_cell, h_entry)
        self.pack_in_cell(w_cell, w_entry)
        self.pack_in_cell(q_cell, q_entry)

        note_cell = self.create_calc_cell(frame, 4, bg)
        tk.Label(note_cell, textvariable=note_var, anchor="center", bg=bg, fg="#7f8c8d").pack(fill=tk.BOTH, expand=True)

        result_cell = self.create_calc_cell(frame, 5, bg)
        tk.Label(result_cell, textvariable=result_var, anchor="center", bg=bg, fg="#e67e22", font=("Arial", 10, "bold")).pack(fill=tk.BOTH, expand=True)

        status_cell = self.create_calc_cell(frame, 6, bg)
        tk.Label(status_cell, textvariable=status_var, anchor="center", bg=bg, fg="#2c3e50").pack(fill=tk.BOTH, expand=True)

        action_cell = self.create_calc_cell(frame, 7, bg)
        ttk.Button(action_cell, text="删除", width=6, command=lambda: self.remove_calc_row(frame)).pack(expand=True, padx=6, pady=4)

        row = {
            "row_kind": "normal",
            "frame": frame,
            "display_name": display_name,
            "base_type": base_type,
            "h": h_var,
            "w": w_var,
            "q": q_var,
            "discount": note_var,
            "res": result_var,
            "status": status_var,
            "h_entry": h_entry,
            "w_entry": w_entry,
        }
        self.calc_rows.append(row)
        self.watch_quote_row(row)
        self.set_row_dimension_state(row, single)

    def add_discount_calc_row(self, display_name):
        frame, bg = self.create_calc_row_frame("discount")

        h_var = tk.StringVar(value="")
        w_var = tk.StringVar(value="")
        q_var = tk.StringVar(value="")
        discount_choice_var = tk.StringVar(value="90%")
        discount_custom_var = tk.StringVar(value="90")
        result_var = tk.StringVar(value="0.00")
        status_var = tk.StringVar(value="未计算")

        name_cell = self.create_calc_cell(frame, 0, bg)
        tk.Label(name_cell, text=display_name, anchor="w", bg=bg, fg="#8a5a00", font=("Arial", 10, "bold")).pack(fill=tk.BOTH, expand=True, padx=8)

        h_cell = self.create_calc_cell(frame, 1, bg)
        w_cell = self.create_calc_cell(frame, 2, bg)
        q_cell = self.create_calc_cell(frame, 3, bg)
        h_entry = ttk.Entry(h_cell, textvariable=h_var, justify="center", state="disabled")
        w_entry = ttk.Entry(w_cell, textvariable=w_var, justify="center", state="disabled")
        q_entry = ttk.Entry(q_cell, textvariable=q_var, justify="center", state="disabled")
        self.pack_in_cell(h_cell, h_entry)
        self.pack_in_cell(w_cell, w_entry)
        self.pack_in_cell(q_cell, q_entry)

        discount_cell = self.create_calc_cell(frame, 4, bg)
        discount_box = tk.Frame(discount_cell, bg=bg)
        discount_box.pack(fill=tk.BOTH, expand=True, padx=5, pady=4)
        discount_combo = ttk.Combobox(
            discount_box,
            textvariable=discount_choice_var,
            values=self.DISCOUNT_CHOICES,
            width=7,
            state="readonly",
        )
        discount_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        vcmd = (self.root.register(self.validate_discount_key), "%P")
        custom_entry = ttk.Entry(discount_box, textvariable=discount_custom_var, width=6, justify="center", validate="key", validatecommand=vcmd)
        custom_entry.pack(side=tk.LEFT, padx=(5, 2))
        tk.Label(discount_box, text="%", bg=bg, fg="#7f8c8d").pack(side=tk.LEFT)

        result_cell = self.create_calc_cell(frame, 5, bg)
        tk.Label(result_cell, textvariable=result_var, anchor="center", bg=bg, fg="#c0392b", font=("Arial", 10, "bold")).pack(fill=tk.BOTH, expand=True)

        status_cell = self.create_calc_cell(frame, 6, bg)
        tk.Label(status_cell, textvariable=status_var, anchor="center", bg=bg, fg="#2c3e50").pack(fill=tk.BOTH, expand=True)

        action_cell = self.create_calc_cell(frame, 7, bg)
        ttk.Button(action_cell, text="删除", width=6, command=lambda: self.remove_calc_row(frame)).pack(expand=True, padx=6, pady=4)

        row = {
            "row_kind": "discount",
            "frame": frame,
            "display_name": display_name,
            "base_type": self.SPECIAL_DISCOUNT_TYPE,
            "h": h_var,
            "w": w_var,
            "q": q_var,
            "discount": discount_choice_var,
            "discount_choice": discount_choice_var,
            "discount_custom": discount_custom_var,
            "custom_entry": custom_entry,
            "res": result_var,
            "status": status_var,
            "h_entry": h_entry,
            "w_entry": w_entry,
        }
        self.calc_rows.append(row)
        self.watch_quote_row(row)
        discount_combo.bind("<<ComboboxSelected>>", lambda _event, r=row: self.update_discount_editor_state(r))
        custom_entry.bind("<FocusOut>", lambda _event, v=discount_custom_var: self.normalize_discount_entry(v))
        self.update_discount_editor_state(row)

    def set_row_dimension_state(self, row, single):
        if row.get("row_kind") == "discount":
            return
        state = "disabled" if single else "normal"
        row["h_entry"].configure(state=state)
        row["w_entry"].configure(state=state)
        if single:
            row["h"].set("")
            row["w"].set("")

    def update_calc_row_states(self, config):
        for row in self.calc_rows:
            if row.get("row_kind") == "discount":
                continue
            item = config.get(row["base_type"])
            if item is not None:
                self.set_row_dimension_state(row, item.get("single", False))
                row["discount"].set("—")
            else:
                row["discount"].set("需检查")

    def remove_calc_row(self, frame):
        for idx, row in enumerate(self.calc_rows):
            if row["frame"] == frame:
                row["frame"].destroy()
                self.calc_rows.pop(idx)
                break
        self.quote_input_changed()


    def render_issues(self, issues):
        if not hasattr(self, "issue_tree"):
            return

        for item in self.issue_tree.get_children():
            self.issue_tree.delete(item)

        for issue in issues:
            level = issue["级别"]
            self.issue_tree.insert(
                "",
                tk.END,
                values=(level, issue["位置"], issue["字段"], issue["输入内容"], issue["提示"]),
                tags=(level,),
            )

        error_count = sum(1 for issue in issues if issue["级别"] == "错误")
        warn_count = len(issues) - error_count
        if error_count:
            self.issue_summary_var.set(f"发现 {error_count} 个错误、{warn_count} 个提醒。请先处理错误；整单没有有效金额，禁止正式导出和截图。")
            self.notebook.tab(self.feedback_page, text=f" 输入反馈 ({error_count}) ")
        elif warn_count:
            self.issue_summary_var.set(f"发现 {warn_count} 个提醒。系统仍会计算，但建议人工确认。")
            self.notebook.tab(self.feedback_page, text=f" 输入反馈 ({warn_count}) ")
        else:
            self.issue_summary_var.set("暂无输入问题。")
            self.notebook.tab(self.feedback_page, text=" 输入反馈 ")


    def reset(self):
        for row in self.calc_rows:
            row["frame"].destroy()
        self.calc_rows = []
        self.quote_input_changed()
        self.calc_table_next_row = 1
        self.last_export_records = []
        self.validation_issues = []
        if hasattr(self, "profit_tree"):
            for item in self.profit_tree.get_children():
                self.profit_tree.delete(item)
        self.render_issues([])
        self.total_val.set("总计：0.00 元")
        self.summary_income.set("0.00")
        self.summary_cost.set("0.00")
        self.summary_profit.set("0.00")
        self.summary_margin.set("0%")
        self.set_feedback("已清空计算列表。", is_error=False)


    # ---------- Excel 记录 / 读取 / 统算 ----------

    def setup_excel_page(self):
        wrapper = ttk.Frame(self.excel_page, padding=12)
        wrapper.pack(fill=tk.BOTH, expand=True)

        self.excel_list_frame = ttk.Frame(wrapper)
        self.excel_detail_frame = ttk.Frame(wrapper)

        # 上一层：只提供 Excel 查看，不提供删除、备注或利润统算。
        list_top = ttk.Frame(self.excel_list_frame)
        list_top.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(list_top, text="Excel 记录查看", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Button(list_top, text="刷新列表", command=self.refresh_excel_files).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(list_top, text="选择 Excel 查看", command=self.browse_excel_file).pack(side=tk.RIGHT, padx=(6, 0))

        self.install_storage_controls(self.excel_list_frame)

        list_body = ttk.Frame(self.excel_list_frame)
        list_body.pack(fill=tk.BOTH, expand=True)
        columns = ("file", "mtime", "rows", "status")
        self.excel_file_tree = ttk.Treeview(list_body, columns=columns, show="headings", height=18)
        headings = {"file": "文件名", "mtime": "修改时间", "rows": "可查看明细行", "status": "读取状态"}
        widths = {"file": 520, "mtime": 170, "rows": 120, "status": 420}
        for col in columns:
            self.excel_file_tree.heading(col, text=headings[col])
            self.excel_file_tree.column(col, width=widths[col], anchor=tk.W if col == "file" else tk.CENTER)
        y_scroll = ttk.Scrollbar(list_body, orient="vertical", command=self.excel_file_tree.yview)
        x_scroll = ttk.Scrollbar(list_body, orient="horizontal", command=self.excel_file_tree.xview)
        self.excel_file_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.excel_file_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        list_body.rowconfigure(0, weight=1)
        list_body.columnconfigure(0, weight=1)
        self.excel_file_tree.bind("<Double-1>", lambda _event: self.open_selected_excel_from_list())

        list_actions = ttk.Frame(self.excel_list_frame)
        list_actions.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(list_actions, text="查看选中 Excel", command=self.open_selected_excel_from_list).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(list_actions, text="双击文件也可以查看。", foreground="#7f8c8d").pack(side=tk.LEFT, padx=12)

        # 下一层：单个 Excel 只读查看。
        detail_top = ttk.Frame(self.excel_detail_frame)
        detail_top.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(detail_top, text="Excel 查看", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Button(detail_top, text="返回上一层", command=self.show_excel_list).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(detail_top, text="查看另一个 Excel", command=self.browse_excel_file).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(detail_top, text="作废选中订单", command=self.delete_current_excel_row, state="disabled").pack(side=tk.RIGHT, padx=(6, 0))

        selected_box = ttk.LabelFrame(self.excel_detail_frame, text="当前文件", padding=8, style="Section.TLabelframe")
        selected_box.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(selected_box, textvariable=self.excel_selected_file, foreground="#2c3e50", wraplength=1080).pack(anchor=tk.W)

        sheet_bar = ttk.Frame(self.excel_detail_frame)
        sheet_bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(sheet_bar, text="工作表：").pack(side=tk.LEFT)
        self.excel_sheet_combo = ttk.Combobox(sheet_bar, textvariable=self.excel_sheet_var, width=28, state="readonly")
        self.excel_sheet_combo.pack(side=tk.LEFT, padx=(4, 8))
        ttk.Button(sheet_bar, text="读取", command=self.load_current_excel_sheet).pack(side=tk.LEFT)
        ttk.Label(sheet_bar, text="只显示：淘宝ID、订单号、微信号、记录时间、项目名称、基础类型、高、宽、数量、销售单价、折扣、销售额、折前销售额、总销售额。", foreground="#7f8c8d").pack(side=tk.LEFT, padx=10)

        self.install_excel_pagination(self.excel_detail_frame)
        view_body = ttk.Frame(self.excel_detail_frame)
        view_body.pack(fill=tk.BOTH, expand=True)
        self.excel_view_tree = ttk.Treeview(view_body, show="headings", height=16, selectmode="browse")
        view_y = ttk.Scrollbar(view_body, orient="vertical", command=self.excel_view_tree.yview)
        view_x = ttk.Scrollbar(view_body, orient="horizontal", command=self.excel_view_tree.xview)
        self.excel_view_tree.configure(yscrollcommand=view_y.set, xscrollcommand=view_x.set)
        self.excel_view_tree.grid(row=0, column=0, sticky="nsew")
        view_y.grid(row=0, column=1, sticky="ns")
        view_x.grid(row=1, column=0, sticky="ew")
        view_body.rowconfigure(0, weight=1)
        view_body.columnconfigure(0, weight=1)
        self.excel_sheet_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_current_excel_sheet())

        remark_box = ttk.LabelFrame(self.excel_detail_frame, text="备注（先选择一行，再保存到同组底部）", padding=8, style="Section.TLabelframe")
        remark_box.pack(fill=tk.X, pady=(8, 0))
        self.excel_remark_text = tk.Text(remark_box, height=3, wrap="word")
        self.excel_remark_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(remark_box, text="追加备注", command=self.save_current_excel_remark, state="disabled").pack(side=tk.RIGHT, padx=(8, 0))

        self.show_excel_list()
        self.schedule_quote_callback(self.refresh_excel_files, delay=300)

    def show_excel_list(self):
        self.excel_detail_frame.pack_forget()
        self.excel_list_frame.pack(fill=tk.BOTH, expand=True)
        self.refresh_excel_files()

    def show_excel_detail(self):
        self.excel_list_frame.pack_forget()
        self.excel_detail_frame.pack(fill=tk.BOTH, expand=True)





    def browse_excel_file(self):
        self.ensure_directories()
        path = filedialog.askopenfilename(
            title="选择要查看的 Excel",
            initialdir=os.path.abspath(self.report_dir),
            filetypes=[("Excel 文件", "*.xlsx"), ("所有文件", "*.*")],
        )
        if path:
            self.open_excel_path(path)

    def open_selected_excel_from_list(self):
        selected = self.excel_file_tree.selection()
        if not selected:
            messagebox.showwarning("未选择", "请先选择一个 Excel 文件。")
            return
        self.open_excel_path(selected[0])

    def open_excel_path(self, path):
        return BackgroundApplicationMixin.open_excel_path(self, path)


    def load_current_excel_sheet(self):
        return BackgroundApplicationMixin.load_current_excel_sheet(self)


    def get_excel_id_column(self, headers):
        return headers.get("淘宝ID") or headers.get("用户")

    def style_excel_sheet(self, ws, header_row=None, freeze=None, widths=None):
        title_fill = PatternFill("solid", fgColor="1F4E78")
        header_fill = PatternFill("solid", fgColor="D9EAF7")
        white_font = Font(color="FFFFFF", bold=True, size=14)
        header_font = Font(bold=True)
        thin = Side(style="thin", color="D9D9D9")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        if ws.max_row >= 1:
            ws["A1"].font = white_font
            ws["A1"].fill = title_fill
            ws["A1"].alignment = Alignment(horizontal="left")

        if header_row:
            for cell in ws[header_row]:
                cell.font = header_font
                cell.fill = header_fill
                cell.border = border
                cell.alignment = Alignment(horizontal="center", vertical="center")

        for row in ws.iter_rows():
            for cell in row:
                cell.border = border
                cell.alignment = Alignment(vertical="center", wrap_text=True)

        if freeze:
            ws.freeze_panes = freeze

        if header_row and ws.max_column:
            last_col = get_column_letter(ws.max_column)
            ws.auto_filter.ref = f"A{header_row}:{last_col}{ws.max_row}"

        if widths:
            for col, width in widths.items():
                ws.column_dimensions[col].width = width
        else:
            for col_idx in range(1, ws.max_column + 1):
                col_letter = get_column_letter(col_idx)
                max_len = 10
                for cell in ws[col_letter]:
                    value = "" if cell.value is None else str(cell.value)
                    max_len = max(max_len, min(len(value) + 2, 40))
                ws.column_dimensions[col_letter].width = max_len


    def get_selected_excel_row_index(self):
        selected = self.excel_view_tree.selection() if hasattr(self, "excel_view_tree") else []
        if not selected:
            return None
        return self.excel_view_row_map.get(selected[0])




    def ensure_excel_remark_column(self, ws, headers, header_row):
        remark_col = headers.get("备注")
        if remark_col:
            return remark_col
        remark_col = (ws.max_column or 0) + 1
        ws.cell(row=header_row, column=remark_col, value="备注")
        headers["备注"] = remark_col
        try:
            ws.column_dimensions[get_column_letter(remark_col)].width = 45
            ws.cell(row=header_row, column=remark_col).font = Font(bold=True)
            ws.cell(row=header_row, column=remark_col).fill = PatternFill("solid", fgColor="D9EAF7")
        except Exception:
            pass
        return remark_col




    def get_daily_excel_path(self):
        """每天只创建一个 Excel：利润明细_YYYYMMDD.xlsx。"""
        date_text = time.strftime("%Y%m%d")
        return os.path.join(self.report_dir, f"{DAILY_EXCEL_PREFIX}_{date_text}.xlsx")







    def style_daily_profit_sheet(self, ws):
        """设置当天利润明细表样式。"""
        header_row, _headers = self.find_excel_table_header(ws)
        if not header_row:
            header_row = 6
        for row in range(header_row + 1, ws.max_row + 1):
            for name in ("高度(m)", "宽度(m)", "数量", "销售单价", "成本单价", "K系数", "折前销售额", "销售额", "总成本", "利润"):
                if name in _headers:
                    ws.cell(row, _headers[name]).number_format = "#,##0.00"
            for name in ("折扣系数", "利润率"):
                if name in _headers:
                    ws.cell(row, _headers[name]).number_format = "0.0%"
            for name, col in _headers.items():
                if name.endswith("原文") or name in ("淘宝ID", "订单号", "微信号", "备注"):
                    ws.cell(row, col).number_format = "@"
        for col in [2, 4, 6]:
            ws.cell(row=4, column=col).number_format = "#,##0.00"
        widths = {
            "A": 20, "B": 16, "C": 18, "D": 16, "E": 28, "F": 16, "G": 10, "H": 10,
            "I": 10, "J": 10, "K": 12, "L": 12, "M": 10, "N": 12, "O": 12, "P": 14,
            "Q": 14, "R": 14, "S": 14, "T": 10, "U": 14, "V": 14, "W": 14, "X": 16,
            "Y": 16, "Z": 14,
        }
        self.style_excel_sheet(ws, header_row=header_row, freeze=f"A{header_row + 1}", widths=widths)
        try:
            if "A1:Z1" not in [str(rng) for rng in ws.merged_cells.ranges]:
                ws.merge_cells("A1:Z1")
        except Exception:
            pass
        ws.row_dimensions[1].height = 24


    # ---------- 截图 ----------

    def get_daily_screenshot_dir(self):
        """截图按天分文件夹保存，例如：截图/20260529。"""
        day_folder = time.strftime("%Y%m%d")
        return os.path.join(self.image_dir, day_folder)

    def build_unique_screenshot_path(self, folder):
        """截图文件名按淘宝ID + 订单号保存；重名时自动追加序号，避免覆盖。"""
        taobao_id = self.clean_filename(self.user_name.get())
        order_no = self.clean_filename(self.order_no.get())
        if not order_no or order_no == "默认淘宝ID":
            order_no = "未填订单号"

        base_name = f"{taobao_id}_{order_no}"
        image_path = os.path.join(folder, f"{base_name}.png")
        if not os.path.exists(image_path):
            return image_path

        index = 2
        while True:
            candidate = os.path.join(folder, f"{base_name}_{index}.png")
            if not os.path.exists(candidate):
                return candidate
            index += 1


if __name__ == "__main__":
    root = tk.Tk()
    app = PriceCalculator(root)
    root.mainloop()
