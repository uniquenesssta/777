"""P02-01 adapter checks against actual baseline classes with control doubles.

No Tk windows, export, screenshot, real prices or production paths are used.
Full application routing is implemented and accepted later in P02-04.
"""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import baseline_check
from quote_core import calculate_quote, capture_legacy_quote


class LegacySnapshotAdapterTests(unittest.TestCase):
    def test_both_actual_legacy_classes_supply_the_same_immutable_core_input(self):
        spec = importlib.util.spec_from_file_location("p02_legacy_examples", ROOT / "docs/baseline/p01_02_examples.py")
        examples = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(examples)
        manifest = json.loads((ROOT / "docs/baseline/manifest.json").read_text(encoding="utf-8"))
        suite = json.loads((ROOT / "docs/baseline/p01-04-golden.json").read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            inspected = baseline_check.inspect_source(ROOT, entry)
            self.assertEqual(inspected["status"], "ok")
            with tempfile.TemporaryDirectory(prefix="777-p02-adapter-") as folder:
                namespace = baseline_check.sandbox_namespace(ROOT, entry, Path(folder))
                original_instance = examples.audit.instance
                for case_id in ("E01", "E03", "E05", "E14"):
                    with self.subTest(role=entry["role"], case=case_id):
                        created = []
                        def capture_instance(*args):
                            obj = original_instance(*args)
                            created.append(obj)
                            return obj
                        source = next(c for c in examples.CASES if c[0] == case_id)
                        with patch.object(examples.audit, "instance", side_effect=capture_instance):
                            examples.original(namespace, Path(folder), source[2])
                        obj = created[0]
                        inputs = capture_legacy_quote(obj.calc_rows, obj.last_config_snapshot,
                                                      price_version_id="isolated-v1")
                        result = calculate_quote(*inputs)
                        expected = next(c["expected"] for c in suite["cases"] if c["id"] == case_id)
                        self.assertEqual(result.display(), expected)
                        if case_id == "E03":
                            self.assertEqual(obj.summary_income.get(), "0.01")
                            self.assertEqual(result.totals.display()["income"], "0.02")


if __name__ == "__main__":
    unittest.main()
