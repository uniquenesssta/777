"""P01-01 baseline inspection and Windows GUI smoke, without production I/O.

Default: inspect source and local dependency versions, print JSON.
--gui-smoke: start both original applications with temporary data directories.
--launch manager|sales: manually inspect one application in a temporary sandbox.
Only --output writes a persistent report; original source is never modified.
"""
import argparse
import ast
import hashlib
import importlib
import importlib.metadata
import json
import platform
from pathlib import Path
import struct
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "baseline" / "manifest.json"


def source_path(root, entry):
    """Explicit P01 archive mapping, never fallback after a failed hash gate."""
    mapping = root / "docs/baseline/source-location.json"
    if not mapping.exists():
        return root / entry["path"]  # Older checkouts and isolated gate fixtures.
    locations = json.loads(mapping.read_text(encoding="utf-8"))["paths"]
    path = root / locations[entry["path"]]
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Baseline source mapping escapes repository")
    return path


def inspect_source(root, entry):
    path = source_path(root, entry)
    result = {"role": entry["role"], "path": entry["path"],
              "diagnostic_source_path": str(path.relative_to(root))}
    try:
        data = path.read_bytes()
        result["git_blob_sha1"] = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest()
        result["sha256"] = hashlib.sha256(data).hexdigest()
        exact_match = (
            result["git_blob_sha1"] == entry["git_blob_sha1"]
            and result["sha256"] == entry["sha256"]
        )
        # Git may check LF blobs out as CRLF on Windows. Keep the raw hashes,
        # and accept only that byte transformation; do not ignore other edits.
        normalized = data.replace(b"\r\n", b"\n")
        result["normalized_git_blob_sha1"] = hashlib.sha1(
            b"blob " + str(len(normalized)).encode() + b"\0" + normalized
        ).hexdigest()
        result["normalized_sha256"] = hashlib.sha256(normalized).hexdigest()
        normalized_match = (
            result["normalized_git_blob_sha1"] == entry["git_blob_sha1"]
            and result["normalized_sha256"] == entry["sha256"]
        )
        result["baseline_matches"] = exact_match or normalized_match
        result["baseline_match_kind"] = (
            "exact" if exact_match else "line_endings_only" if normalized_match else "changed"
        )
        ast.parse(data.decode("utf-8"), filename=str(path))
        result["syntax"] = "valid"
        result["status"] = "ok" if result["baseline_matches"] else "changed"
    except (OSError, UnicodeError, SyntaxError) as exc:
        result.update(status="error", error=f"{type(exc).__name__}: {exc}")
    return result


def inspect_dependency(entry):
    result = {"module": entry["module"], "required_for": entry["required_for"]}
    try:
        module = importlib.import_module(entry["module"])
        distribution = entry["distribution"]
        if distribution:
            result["version"] = importlib.metadata.version(distribution)
        else:
            # Tcl interpreter needs no display. Creating a Tk window is separate.
            result["tcl_runtime_version"] = module.Tcl().eval("info patchlevel")
            result["tk_compiled_version"] = str(module.TkVersion)
        result["status"] = "available"
    except Exception as exc:
        result.update(status="unavailable", error=f"{type(exc).__name__}: {exc}")
    return result


def inspect_environment(root=ROOT):
    manifest = json.loads((root / "docs/baseline/manifest.json").read_text(encoding="utf-8"))
    system = platform.system()
    try:
        packager = {"pyinstaller_version": importlib.metadata.version("pyinstaller")}
    except importlib.metadata.PackageNotFoundError:
        packager = {"pyinstaller_version": None, "status": "not_installed; source startup does not require packaging tools"}
    return {
        "task": "P01-01",
        "scope": "Immutable P01 originals from diagnostic_source_path; current GUI checks use tools/p02_gui_check.py",
        "source_commit": manifest["source_commit"],
        "environment": {
            "os": system,
            "release": platform.release(),
            "architecture": platform.machine(),
            "python_bits": struct.calcsize("P") * 8,
            "python": platform.python_version(),
            "python_executable": sys.executable,
            "target_windows": system == "Windows",
        },
        "sources": [inspect_source(root, entry) for entry in manifest["files"]],
        "dependencies": [inspect_dependency(entry) for entry in manifest["dependencies"]],
        "resources": [
            {**entry, "present_in_repository": (root / entry["path"]).is_file()}
            for entry in manifest["resources"]
        ],
        "gui": {"status": "not_run"},
        "packaging_environment": packager,
        "production_paths_accessed": False,
        "windows_acceptance": "pending",
    }


def sandbox_namespace(root, entry, sandbox):
    """Load original definitions, override only storage constants before init."""
    source = inspect_source(root, entry)
    if source["status"] != "ok":
        raise ValueError(f"Source differs from P01-01 baseline: {entry['path']}")
    path = source_path(root, entry)
    namespace = {"__name__": "p01_baseline_sandbox", "__file__": str(path)}
    exec(compile(path.read_bytes(), str(path), "exec"), namespace)
    report_dir = sandbox / "reports"
    image_dir = sandbox / "screenshots"
    config = sandbox / "config.json"
    report_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)
    # One known single-item fixture, sufficient for startup/calculation smoke.
    # Full business golden cases belong to P01-04, not this baseline task.
    config.write_text(json.dumps({"items": [
        {"name": "P01样本支架", "sale": "50", "cost": "20", "k": "1", "single": True}
    ]}, ensure_ascii=False), encoding="utf-8")
    namespace["APP_SAVE_ROOT"] = str(sandbox)
    if entry["role"] == "manager":
        namespace.update(
            DEFAULT_REPORT_DIR=str(report_dir),
            DEFAULT_CONFIG_FILE=str(config),
            DEFAULT_SCREENSHOT_DIR=str(image_dir),
        )
    else:
        namespace.update(
            LAN_DATA_DIR=str(report_dir),
            LAN_PRICE_CONFIG_FILE=str(config),
            LAN_SCREENSHOT_DIR=str(image_dir),
        )
    return namespace


def sandbox_application_type(namespace, sandbox):
    """Guard interactive directory/file choices in the diagnostic session only."""
    original = namespace["PriceCalculator"]
    def contained(path):
        if not Path(path).resolve().is_relative_to(sandbox.resolve()):
            raise ValueError("P01-01隔离检查只允许访问临时目录；请勿选择实际账本或导出目录")
    class SandboxedApplication(original):
        def ensure_directories(self):
            contained(self.report_dir)
            contained(self.image_dir)
            return super().ensure_directories()

        def save_settings(self):
            contained(self.config_file)
            return super().save_settings()

        def apply_export_dir(self):
            contained(self.normalize_path_text(self.export_dir_var.get()))
            return super().apply_export_dir()

        def open_excel_path(self, path):
            contained(path)
            return super().open_excel_path(path)
    return SandboxedApplication


def run_gui(root, entry, manual=False):
    result = {"role": entry["role"], "mode": "manual" if manual else "automatic_smoke"}
    window = None
    with tempfile.TemporaryDirectory(prefix="777-p01-") as folder:
        sandbox = Path(folder)
        try:
            namespace = sandbox_namespace(root, entry, sandbox)
            tk = namespace["tk"]
            window = tk.Tk()
            callback_errors = []
            def callback_error(error_type, value, _traceback):
                callback_errors.append(f"{error_type.__name__}: {value}")
            window.report_callback_exception = callback_error
            app_type = sandbox_application_type(namespace, sandbox)
            app = app_type(window)
            for value in (app.report_dir, app.image_dir):
                if not Path(value).resolve().is_relative_to(sandbox.resolve()):
                    raise ValueError("Application storage escaped temporary sandbox")
            config_path = getattr(app, "price_config_file", app.config_file)
            if not Path(config_path).resolve().is_relative_to(sandbox.resolve()):
                raise ValueError("Application price source escaped temporary sandbox")
            window.title("P01-01 隔离检查 — " + window.title())
            result["startup"] = "ok"
            result["tabs"] = [app.notebook.tab(tab, "text").strip() for tab in app.notebook.tabs()]
            if manual:
                print("隔离窗口已打开：所有配置、Excel和截图均在临时目录，关闭后自动清理。", file=sys.stderr)
                window.mainloop()
                result.update(status="manual_session_finished", acceptance="requires_user_observation")
            else:
                def smoke():
                    try:
                        if callback_errors:
                            raise RuntimeError("Tk callback failed: " + "; ".join(callback_errors))
                        expected_tabs = 5 if entry["role"] == "manager" else 3
                        if len(result["tabs"]) != expected_tabs:
                            raise AssertionError("Unexpected application page count")
                        app.add_calc_row("P01样本支架", "P01样本支架", True)
                        app.calc_rows[-1]["q"].set("1")
                        app.calculate(notify=False)
                        amounts = [app.summary_income.get(), app.summary_cost.get(), app.summary_profit.get()]
                        if amounts != ["50.00", "20.00", "30.00"] or app.validation_issues:
                            raise AssertionError(f"Startup sample mismatch: {amounts}")
                        result["single_item_smoke"] = amounts
                        app.on_close()
                        result.update(status="passed", close="ok")
                    except Exception as exc:
                        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                        try:
                            window.destroy()
                        except Exception:
                            pass
                window.after(600, smoke)
                window.mainloop()
                result["scope"] = "original GUI startup/event loop/one calculation/close in temporary directories"
        except Exception as exc:
            result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            if window is not None:
                try:
                    window.destroy()
                except Exception:
                    pass
    result["sandbox_cleaned"] = not sandbox.exists()
    return result


def emit(report, output=None):
    data = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output:
        output = output.resolve()
        # Reports must not overwrite tracked source/documents or prior reports.
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            handle.write(data)
    print(data, end="")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--gui-smoke", action="store_true", help="Windows: test both original GUIs in temporary folders")
    action.add_argument("--launch", choices=("manager", "sales"), help="Windows: open one original GUI in a temporary sandbox")
    parser.add_argument("--output", type=Path, help="Create a new JSON report file; existing files are never overwritten")
    args = parser.parse_args(argv)
    report = inspect_environment()
    failures = [s for s in report["sources"] if s["status"] != "ok"]
    required = [d for d in report["dependencies"] if d["status"] != "available" and d["module"] in ("tkinter", "openpyxl")]
    code = 1 if failures or required else 0
    if args.gui_smoke or args.launch:
        if not report["environment"]["target_windows"]:
            report["gui"] = {"status": "blocked", "reason": "Windows target environment required; no Linux/macOS GUI acceptance"}
            code = 2
        elif failures or required:
            report["gui"] = {"status": "blocked", "reason": "Source baseline or startup/Excel dependency check failed"}
            code = 1
        else:
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
            selected = [e for e in manifest["files"] if not args.launch or e["role"] == args.launch]
            results = [run_gui(ROOT, e, manual=bool(args.launch)) for e in selected]
            report["gui"] = {"status": "failed" if any(r["status"] == "failed" for r in results) else "completed", "applications": results}
            code = 1 if report["gui"]["status"] == "failed" else 0
            # This automated check is narrow; business/deployment acceptance stays pending.
            if args.gui_smoke and code == 0:
                report["windows_acceptance"] = "isolated_gui_smoke_passed; deployed_environment_and_user_acceptance_pending"
    try:
        emit(report, args.output)
    except OSError as exc:
        print(f"Report write failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
