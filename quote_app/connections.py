"""Visible local connection and manager-published storage, independent of prices."""
import os
from pathlib import Path
from tkinter import filedialog, ttk

from quote_files.configuration import save_config
from quote_files.settings import decode_settings, encode_settings, probe_directory
from quote_files.transactions import FileFailure, UnknownCommit, digest, read_bytes
from .storage import path_module, publish_directory, resolve_directory


def default_settings_file(role):
    fallback = Path.home() / "AppData" / "Local" if os.name == "nt" else Path.home() / ".local" / "share"
    base = os.environ.get("LOCALAPPDATA") or str(fallback)
    return str(Path(base) / "QuoteProfitCalculator" / (role + "-settings.json"))


def absolute_root(text):
    text = text.strip()
    module = path_module(text)
    if not text or any(ord(c) < 32 for c in text) or len(text) > 32767 or not module.isabs(text):
        raise FileFailure("请选择完整的本机或UNC数据源路径")
    drive, tail = module.splitdrive(text)
    if module.__name__ == "ntpath" and (not drive or (tail and not tail.startswith(("/", "\\")))):
        raise FileFailure("不支持根相对或盘符相对路径")
    return module.normpath(text)


class ConnectionMixin:
    def initialize_connections(self):
        self.data_root = ""
        self._local_hash = self._shared_hash = None
        self._local_bad = self._shared_bad = False
        self._storage_valid = False
        self._settings_pending = None
        self.config_file = self.report_dir = self.image_dir = ""
        self.data_source_var = self._new_text_var("")
        self.backup_dir_var = self._new_text_var("")
        self.price_file_var = self._new_text_var("config.json")
        self.screenshot_dir_var = self._new_text_var("")
        self.config_source_var = self._new_text_var("")
        self.storage_status_var = self._new_text_var("尚未连接数据源，请选择目录并保存连接。")
        self.export_dir_var.set("")
        try:
            raw = read_bytes(self.local_settings_file)
            if raw is not None:
                data = decode_settings(raw, "local")
                root = absolute_root(data["data_root"])
                if data["backup_dir"]:
                    absolute_root(data["backup_dir"])
                self._local_hash = digest(raw)
                self.data_root = root
                self.config_file = path_module(root).join(root, "config.json")
                self.config_source_var.set(self.config_file)
                self.data_source_var.set(root)
                self.backup_dir_var.set(data["backup_dir"])
        except (OSError, FileFailure) as exc:
            self._local_bad = True
            self.storage_status_var.set(f"本机设置不可用，原件保留：{exc}")
        self.observe_storage()

    def shared_settings_path(self, root=None):
        root = root or self.data_root
        return path_module(root).join(root, "storage.json")

    def resolve_shared(self, data, root=None):
        anchor = self.shared_settings_path(root)
        return tuple(resolve_directory(data[key], anchor, key, sales=self.quote_role == "sales")
                     for key in ("price_file", "export_dir", "screenshot_dir"))

    def observe_storage(self):
        if not self.data_root:
            return False
        try:
            raw = read_bytes(self.shared_settings_path())
            if raw is None:
                self._shared_bad = False
                raise FileFailure("尚未发布storage.json；请在母版保存共享目录")
            data = decode_settings(raw, "shared")
            paths = self.resolve_shared(data)
        except (OSError, ValueError, FileFailure) as exc:
            self._storage_valid = False
            self._shared_bad = raw is not None if 'raw' in locals() else True
            self.storage_status_var.set(f"共享目录不可用；保留已显示位置，禁止输出：{exc}")
            return False
        if digest(raw) != self._shared_hash or not self._storage_valid or getattr(self, "_storage_version", None) is None:
            previous = self.config_file
            self.config_file, self.report_dir, self.image_dir = paths
            self._shared_hash = digest(raw)
            self._storage_version = self._shared_hash
            self.current_excel_path = None
            self.config_source_var.set(self.config_file)
            self.price_file_var.set(data["price_file"])
            self.export_dir_var.set(self.report_dir)
            self.screenshot_dir_var.set(self.image_dir)
            if previous and previous != self.config_file:
                self._last_config_sha = None
                self._config_pending = None
                self.quote_session.observe_price_source("unavailable")
                self.quote_input_changed()
        self._shared_bad = False
        self._storage_valid = True
        self.storage_status_var.set(f"连接已保存：{self.local_settings_file}；共享目录已确认，子版只读继承。")
        return True

    def install_storage_controls(self, parent):
        box = ttk.LabelFrame(parent, text="数据连接与存储（子版输出目录继承母版）", padding=8)
        box.pack(fill="x", pady=(0, 8))
        self.storage_entries = {}
        fields = [("数据源", self.data_source_var, True), ("价格文件", self.price_file_var, self.quote_role == "manager"),
                  ("价格完整路径", self.config_source_var, False), ("Excel目录", self.export_dir_var, self.quote_role == "manager"),
                  ("截图目录", self.screenshot_dir_var, self.quote_role == "manager")]
        if self.quote_role == "manager":
            fields.append(("主机备份目标（登记）", self.backup_dir_var, True))
        for row, (label, var, editable) in enumerate(fields):
            ttk.Label(box, text=label + "：").grid(row=row, column=0, sticky="w")
            entry = ttk.Entry(box, textvariable=var, state="normal" if editable else "readonly")
            entry.grid(row=row, column=1, sticky="ew", padx=6, pady=2)
            if label != "数据源":
                self.storage_entries[label] = entry
            if editable and label == "价格文件":
                ttk.Button(box, text="选择", command=self.choose_price_file).grid(row=row, column=2)
            elif editable:
                ttk.Button(box, text="选择", command=lambda v=var: self.choose_connection_dir(v)).grid(row=row, column=2)
        row = len(fields)
        ttk.Label(box, textvariable=self.storage_status_var, wraplength=850).grid(row=row, column=0, columnspan=3, sticky="w")
        ttk.Button(box, text="保存本机连接", command=self.apply_connection).grid(row=row+1, column=0, pady=4)
        ttk.Button(box, text="选择旧版目录", command=self.select_legacy_connection).grid(row=row+1, column=1, sticky="w")
        if self.quote_role == "manager":
            ttk.Button(box, text="保存共享目录", command=self.apply_export_dir).grid(row=row+2, column=0, pady=4)
            ttk.Button(box, text="导入旧JSON目录", command=self.import_legacy_directories).grid(row=row+2, column=1, sticky="w")
        ttk.Button(box, text="刷新来源", command=self.reload_price_settings_from_json).grid(row=row+2, column=2)
        ttk.Button(box, text="检查上次写入", command=self.check_last_write).grid(row=row+1, column=2)
        box.columnconfigure(1, weight=1)

    def choose_connection_dir(self, var):
        if self.quote_role == "sales" and var is not self.data_source_var:
            return False
        selected = filedialog.askdirectory(parent=self.root, initialdir=var.get() or str(Path.home()))
        if selected:
            var.set(selected)
        return bool(selected)

    def choose_price_file(self):
        if self.quote_role != "manager":
            return False
        path = filedialog.askopenfilename(parent=self.root, initialdir=self.data_root or str(Path.home()), filetypes=[("价格JSON", "*.json")])
        if path:
            self.price_file_var.set(path)
        return bool(path)

    def select_legacy_connection(self):
        self.data_source_var.set(self.legacy_data_root)
        self.storage_status_var.set("已填入旧版目录；请核对完整路径后保存本机连接。")

    def apply_connection(self):
        try:
            if self._local_bad or self._blocking_file_request:
                raise FileFailure("坏本机设置或未确认写入须先核查，禁止覆盖/切源")
            if any(p and p.get("unknown") for p in (self._excel_pending, self._edit_pending)):
                raise FileFailure("存在未确认写入，请先检查上次写入")
            root = absolute_root(self.data_source_var.get())
            backup = self.backup_dir_var.get().strip() if self.quote_role == "manager" else ""
            if backup:
                backup = absolute_root(backup)
            if not Path(root).is_dir():
                raise FileFailure("数据源目录不存在；请选择已有目录")
            shared_raw = read_bytes(self.shared_settings_path(root))
            if shared_raw is not None:
                self.resolve_shared(decode_settings(shared_raw, "shared"), root)
            elif self.quote_role == "sales":
                raise FileFailure("母版尚未发布共享目录，无法连接")
            raw = encode_settings({"schema": "777-local-v1", "data_root": root, "backup_dir": backup}, "local")
            Path(self.local_settings_file).parent.mkdir(parents=True, exist_ok=True)
            self._save_setting_bytes(self.local_settings_file, raw, "local", self._local_hash)
            changed = root != self.data_root
            self._local_hash = digest(raw)
            self.data_root = root
            self.data_source_var.set(root)
            if changed:
                self._shared_hash = None
                self.active_price_config = None
                self._last_config_sha = None
                self.quote_session.observe_price_source("unavailable")
                self.quote_input_changed()
                self._excel_pending = self._config_pending = self._edit_pending = None
            if shared_raw is None:
                self.config_file = path_module(root).join(root, "config.json")
                self.config_source_var.set(self.config_file)
                self.price_file_var.set("config.json")
                self.export_dir_var.set(path_module(root).join(root, "利润表"))
                self.screenshot_dir_var.set(path_module(root).join(root, "截图"))
            self.observe_storage()
            self.reload_price_settings_from_json(first_load=True, silent=True)
            self.set_feedback("本机连接已保存。目录切换只改变连接，不移动或合并数据；备份目标仅登记。")
            return True
        except (OSError, ValueError, FileFailure) as exc:
            self.set_feedback(f"连接未确认保存：{exc}", is_error=True)
            return False

    def _save_setting_bytes(self, path, raw, kind, expected):
        try:
            pending = self._settings_pending["request"] if self._settings_pending and self._settings_pending["path"] == path else None
            result, req = save_config(path, raw, expected_hash=expected,
                validator=lambda b: decode_settings(b, kind), pending=pending)
            self.last_file_transaction = result
            self._settings_pending = {"path": path, "request": req, "unknown": False}
            return result
        except (OSError, FileFailure) as exc:
            req = getattr(exc, "pending_request", None)
            if req:
                self._settings_pending = {"path": path, "request": req, "unknown": isinstance(exc, UnknownCommit)}
                if isinstance(exc, UnknownCommit):
                    self._blocking_file_request = {"path": path, "request_id": exc.request_id or req.request_id}
            raise

    def apply_export_dir(self):
        if self.quote_role != "manager":
            return False
        try:
            if not self.data_root or self._blocking_file_request:
                raise FileFailure("请先保存本机连接并核查未确认写入")
            if self._shared_bad:
                raise FileFailure("共享目录设置损坏，禁止覆盖；请先核查恢复副本")
            anchor = self.shared_settings_path()
            data = {"schema": "777-shared-v1"}
            for key, var, default in (("price_file", self.price_file_var, "config.json"),
                ("export_dir", self.export_dir_var, "利润表"), ("screenshot_dir", self.screenshot_dir_var, "截图")):
                data[key] = publish_directory(var.get(), anchor, default)
            price, reports, images = self.resolve_shared(data)
            if price == anchor or price in {reports, images} or anchor in {reports, images}:
                raise FileFailure("文件路径与输出文件夹不能相同")
            for folder in (reports, images):
                probe_directory(folder)
            raw = encode_settings(data, "shared")
            self._save_setting_bytes(anchor, raw, "shared", self._shared_hash)
            self.observe_storage()
            self.set_feedback("共享目录已保存；子版自动继承。价格文件未被修改，原数据未移动。")
            try:
                self.refresh_excel_files()
            except Exception as exc:
                self.set_feedback(f"共享目录已保存，但列表刷新失败：{exc}；请手动刷新。", is_error=True)
            return True
        except (OSError, ValueError, FileFailure) as exc:
            self.set_feedback(f"共享目录未确认保存：{exc}；请核查后刷新或重试。", is_error=True)
            return False

    def import_legacy_directories(self):
        if self.quote_role != "manager" or not self.data_root:
            return False
        candidate, _, _ = self._read_price_candidate()
        if candidate is None:
            self.set_feedback("旧JSON不可用，未导入目录。", is_error=True)
            return False
        self.export_dir_var.set(resolve_directory(candidate.export_dir, self._price_path(), "利润表"))
        self.screenshot_dir_var.set(resolve_directory(candidate.screenshot_dir, self._price_path(), "截图"))
        self.storage_status_var.set("旧JSON目录已填入；核对后保存共享目录。原件未改写。")
        return True
