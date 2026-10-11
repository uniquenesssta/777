"""Fault injection and native process locking on synthetic files only.

Running here uses the POSIX auxiliary backend; Windows runs the CRT backend.
No production SMB acceptance is inferred from either local result.
"""
from contextlib import contextmanager
import json
import multiprocessing as mp
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from quote_files import transactions as tx
from quote_files.configuration import save_config


def receipt(raw, rid):
    return json.loads(raw)["requests"].get(rid) if raw else None


def append(path, rid, value, **options):
    fingerprint = tx.digest(json.dumps(value).encode())
    def transform(raw):
        data = json.loads(raw) if raw else {"values": [], "requests": {}}
        result = {"fingerprint": fingerprint, "value": value}
        data["values"].append(value)
        data["requests"][rid] = result
        return json.dumps(data).encode(), result
    return tx.transact(path, rid, fingerprint, "append", transform, receipt, **options)


def concurrent_worker(path, rid, value, start, output):
    start.wait(10)
    for attempt in range(500):
        try:
            result = append(path, rid, value)
            output.put(("ok", result.request_id))
            return
        except tx.FileBusy:
            time.sleep(0.01)  # Explicitly known not submitted, same ID only.
        except Exception as exc:
            output.put(("error", type(exc).__name__, str(exc)))
            return
    output.put(("error", "lock timeout"))


def lock_holder(path, ready):
    with tx.file_lock(path):
        ready.set()
        # Parent kills only this synthetic subprocess to simulate a crash.
        time.sleep(30)


class FileTransactionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="777-p03-files-")
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "中文文件.json"
        self.rid = str(uuid.uuid4())

    def test_receipt_replay_before_stale_version_is_exactly_once(self):
        first = append(self.path, self.rid, "one")
        again = append(self.path, self.rid, "one", expected_hash=None)
        self.assertTrue(again.already_committed)
        self.assertEqual(first.content_sha256, again.content_sha256)
        self.assertEqual(json.loads(self.path.read_bytes())["values"], ["one"])

    def test_request_id_cannot_be_reused_for_other_content(self):
        append(self.path, self.rid, 1)
        original = self.path.read_bytes()
        with self.assertRaises(tx.FileConflict):
            append(self.path, self.rid, 2)
        self.assertEqual(self.path.read_bytes(), original)

    def test_stale_hash_rejects_without_transform(self):
        append(self.path, self.rid, 1)
        before = self.path.read_bytes()
        with self.assertRaises(tx.FileConflict):
            append(self.path, str(uuid.uuid4()), 2, expected_hash=None)
        self.assertEqual(self.path.read_bytes(), before)

    def test_verified_preimage_backup_and_committed_journal(self):
        append(self.path, self.rid, 1)
        before = self.path.read_bytes()
        rid = str(uuid.uuid4())
        append(self.path, rid, 2)
        journal = json.loads(tx.journal_path(self.path, rid).read_bytes())
        self.assertEqual(journal["state"], "committed")
        backup = tx.journal_path(self.path, rid).parent / journal["backup"]
        self.assertEqual(backup.read_bytes(), before)
        self.assertEqual(tx.digest(backup.read_bytes()), journal["before_sha256"])
        self.assertEqual(tx.digest(self.path.read_bytes()), journal["after_sha256"])

    def test_candidate_validation_failure_preserves_original(self):
        append(self.path, self.rid, 1)
        before = self.path.read_bytes()
        def invalid(raw):
            return b'invalid', {"fingerprint": "f"}
        with self.assertRaises(tx.FileFailure):
            tx.transact(self.path, str(uuid.uuid4()), "f", "append", invalid, receipt)
        self.assertEqual(self.path.read_bytes(), before)

    def test_temp_write_failure_preserves_original(self):
        append(self.path, self.rid, 1)
        before = self.path.read_bytes()
        with patch.object(tx, "write_exclusive", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(tx.FileFailure):
                append(self.path, str(uuid.uuid4()), 2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_backup_verification_failure_preserves_original(self):
        append(self.path, self.rid, 1)
        before = self.path.read_bytes()
        real = tx.read_bytes
        def corrupted(path):
            return b'bad backup' if str(path).endswith('.bak') else real(path)
        with patch.object(tx, "read_bytes", side_effect=corrupted):
            with self.assertRaises(tx.FileFailure):
                append(self.path, str(uuid.uuid4()), 2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_replace_denied_is_queryable_and_same_id_can_retry(self):
        append(self.path, self.rid, 1)
        before = self.path.read_bytes()
        rid = str(uuid.uuid4())
        replace = tx.os.replace
        def deny(src, target):
            if Path(target) == self.path:
                raise PermissionError("synthetic Excel occupancy")
            return replace(src, target)
        with patch.object(tx.os, "replace", side_effect=deny):
            with self.assertRaises(tx.UnknownCommit):
                append(self.path, rid, 2)
        self.assertEqual(self.path.read_bytes(), before)
        status = tx.query_request(self.path, rid, receipt)
        self.assertEqual(status["status"], "not_committed")
        append(self.path, rid, 2)
        self.assertEqual(json.loads(self.path.read_bytes())["values"], [1, 2])

    def test_replace_happened_then_exception_returns_known_saved(self):
        replace = tx.os.replace
        def after(src, target):
            replace(src, target)
            if Path(target) == self.path:
                raise OSError("synthetic lost acknowledgment")
        with patch.object(tx.os, "replace", side_effect=after):
            result = append(self.path, self.rid, 1)
        self.assertFalse(result.already_committed)
        self.assertEqual(tx.query_request(self.path, self.rid, receipt)["status"], "committed")
        self.assertTrue(append(self.path, self.rid, 1).already_committed)

    def test_unreadable_after_replace_is_unknown_then_receipt_resolves(self):
        real_read = tx.read_bytes
        calls = 0
        def read(path):
            nonlocal calls
            if Path(path) == self.path:
                calls += 1
                if calls >= 3:  # First read, final CAS, then committed verification.
                    raise OSError("synthetic disconnected share")
            return real_read(path)
        with patch.object(tx, "read_bytes", side_effect=read):
            with self.assertRaises(tx.UnknownCommit) as error:
                append(self.path, self.rid, 1)
        self.assertEqual(error.exception.request_id, self.rid)
        self.assertTrue(Path(error.exception.diagnostic).exists())
        self.assertEqual(tx.query_request(self.path, self.rid, receipt)["status"], "committed")
        append(self.path, self.rid, 1)
        self.assertEqual(json.loads(self.path.read_bytes())["values"], [1])

    def test_journal_failure_after_verified_publish_does_not_report_unsaved(self):
        real_write = tx.write_journal
        def fail_committed(path, state):
            if state["state"] == "committed":
                raise OSError("synthetic journal offline")
            return real_write(path, state)
        with patch.object(tx, "write_journal", side_effect=fail_committed):
            result = append(self.path, self.rid, 1)
        self.assertIsNotNone(result.diagnostic)
        append(self.path, str(uuid.uuid4()), 2)  # Repairs prepared receipt under lock.
        self.assertEqual(json.loads(tx.journal_path(self.path, self.rid).read_bytes())["state"], "committed")

    def test_observed_external_change_is_not_overwritten(self):
        append(self.path, self.rid, 1)
        outside = b'{"values":[99],"requests":{}}'
        real_write = tx.write_journal
        def external_change(path, state):
            real_write(path, state)
            if state["state"] == "prepared":
                self.path.write_bytes(outside)
        with patch.object(tx, "write_journal", side_effect=external_change):
            with self.assertRaises(tx.FileConflict):
                append(self.path, str(uuid.uuid4()), 2)
        self.assertEqual(self.path.read_bytes(), outside)

    def test_unresolved_prepared_request_blocks_new_writer(self):
        append(self.path, self.rid, 1)
        real_read = tx.read_bytes
        count = 0
        def read(path):
            nonlocal count
            if Path(path) == self.path:
                count += 1
                if count >= 3:
                    raise OSError("synthetic lost result")
            return real_read(path)
        with patch.object(tx, "read_bytes", side_effect=read):
            with self.assertRaises(tx.UnknownCommit):
                append(self.path, str(uuid.uuid4()), 2)
        self.path.write_bytes(b'{"values":[999],"requests":{}}')
        before = self.path.read_bytes()
        with self.assertRaises(tx.UnknownCommit):
            append(self.path, str(uuid.uuid4()), 3)
        self.assertEqual(self.path.read_bytes(), before)

    def test_absent_receipt_is_not_proof_of_noncommit(self):
        self.assertEqual(tx.query_request(self.path, self.rid, receipt)["status"], "not_found")

    def test_two_native_process_writers_preserve_both_requests(self):
        ctx = mp.get_context("spawn")
        start, output = ctx.Event(), ctx.Queue()
        children = [ctx.Process(target=concurrent_worker, args=(str(self.path), str(uuid.uuid4()), i, start, output)) for i in (1, 2)]
        try:
            for child in children:
                child.start()
            start.set()
            replies = [output.get(timeout=20) for _ in children]
            for child in children:
                child.join(10)
            self.assertEqual([r[0] for r in replies], ["ok", "ok"])
            self.assertEqual(sorted(json.loads(self.path.read_bytes())["values"]), [1, 2])
            self.assertEqual(len(json.loads(self.path.read_bytes())["requests"]), 2)
        finally:
            for child in children:
                if child.is_alive():
                    child.terminate()
                child.join(5)
            output.close()

    def test_crashed_holder_releases_native_lock_without_deleting_lockfile(self):
        ctx = mp.get_context("spawn")
        ready = ctx.Event()
        child = ctx.Process(target=lock_holder, args=(str(self.path), ready))
        try:
            child.start()
            self.assertTrue(ready.wait(10))
            with self.assertRaises(tx.FileBusy):
                append(self.path, self.rid, 1)
            child.terminate()
            child.join(10)
            append(self.path, self.rid, 1)
            self.assertTrue(self.path.with_name('.' + self.path.name + '.777.lock').exists())
        finally:
            if child.is_alive():
                child.terminate()
            child.join(5)

    def test_config_cas_preserves_other_writer_and_validates_whole_candidate(self):
        self.path.write_bytes(b'{"value":1}')
        before = self.path.read_bytes()
        expected = tx.digest(before)
        self.path.write_bytes(b'{"value":2}')
        with self.assertRaises(tx.FileConflict):
            save_config(self.path, b'{"value":3}', expected_hash=expected, validator=json.loads)
        self.assertEqual(self.path.read_bytes(), b'{"value":2}')
        with self.assertRaises(json.JSONDecodeError):
            save_config(self.path, b'invalid', expected_hash=None, validator=json.loads)
        self.assertEqual(self.path.read_bytes(), b'{"value":2}')

    def test_config_publish_and_effect_idempotency_keep_schema(self):
        self.path.write_bytes(b'{"value":1}')
        before = self.path.read_bytes()
        first, req = save_config(self.path, b'{"value":2}', expected_hash=tx.digest(before), validator=json.loads)
        again, _ = save_config(self.path, b'{"value":2}', expected_hash=tx.digest(before), validator=json.loads, pending=req)
        self.assertTrue(again.already_committed)
        self.assertEqual(json.loads(self.path.read_bytes()), {"value": 2})
        self.assertEqual(tx.query_request(self.path, req.request_id, lambda *_: None)["status"], "committed")
        state = json.loads(tx.journal_path(self.path, req.request_id).read_bytes())
        self.assertEqual((tx.journal_path(self.path, req.request_id).parent / state["backup"]).read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
