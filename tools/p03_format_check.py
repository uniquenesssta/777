"""P03-02 temporary synthetic format/adapter checks; optional Windows GUI smoke."""
import argparse
import hashlib
import io
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "tests")]


def case_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from case_ids(item)
        else:
            yield item.id()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui-smoke", action="store_true", help="also run current mother/sales Tk pair on Windows")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    paths = sorted([*ROOT.glob("quote_files/*.py"), *ROOT.glob("quote_app/*.py"),
                    *ROOT.glob("报价*.py"), ROOT / "tests/test_ledger_reading.py", Path(__file__),
                    ROOT / "tools/p02_gui_check.py", ROOT / "tools/p03_file_check.py"])
    report = {
        "task": "P03-02",
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "environment": {"os": platform.system(), "python": platform.python_version()},
        "implementation_sha256_LF": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in paths},
        "scope": "Temporary synthetic workbooks/current adapter methods and Tcl variables; no production files or shared-machine exercise",
        "production_paths_accessed": False,
        "windows_gui": "not_requested",
        "shared_machine_tests": "not_requested; P03-01 remainder canceled by user",
    }
    suite = unittest.defaultTestLoader.loadTestsFromName("test_ledger_reading")
    ids = list(case_ids(suite))
    log = io.StringIO()
    started = time.monotonic()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    report["checks"] = {"status": "passed" if result.wasSuccessful() else "failed",
        "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "skipped": result.skipped, "elapsed_seconds": round(time.monotonic() - started, 3),
        "test_ids": ids, "log": log.getvalue()}
    report["status"] = report["checks"]["status"]
    if args.gui_smoke:
        if platform.system() != "Windows":
            report["windows_gui"] = "blocked: Windows GUI only"
            report["status"] = "blocked" if result.wasSuccessful() else "failed"
        elif result.wasSuccessful():
            import p02_gui_check as gui
            from p03_file_check import transaction_gui_smoke
            try:
                with patch.object(gui, "shared_directory_smoke", side_effect=transaction_gui_smoke):
                    report["windows_gui"] = gui.run_pair()
                report["status"] = report["windows_gui"]["status"]
            except Exception as exc:
                report["windows_gui"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                report["status"] = "failed"
    from baseline_check import emit
    emit(report, args.output)
    return 2 if report["status"] == "blocked" else int(report["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
