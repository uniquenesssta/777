"""Bounded, disposable per-window ledger index; never a write authority."""
from collections import OrderedDict, Counter
from dataclasses import dataclass
import os
from threading import Event, RLock

from .documents import PARSER_VERSION, failed_document, parse_document
from .metadata import canonical, file_version
from .transactions import digest, read_bytes


@dataclass(frozen=True)
class Entry:
    version: object
    document: object
    parser_version: str


class Scan(dict):
    def __init__(self, results, aggregate):
        super().__init__(results)
        self.aggregate = aggregate


class LedgerCache:
    def __init__(self, *, max_files=64, max_bytes=64 * 1024 * 1024, max_index=2048, index_bytes=16 * 1024 * 1024):
        self.max_files, self.max_bytes = max_files, max_bytes
        self.max_index, self.index_bytes = max_index, index_bytes
        self._lock = RLock()
        self._entries, self._flights, self._generations = OrderedDict(), {}, {}
        self._index = OrderedDict()
        self._totals = {}
        self._epoch, self._weight = 0, 0
        self._index_weight = 0
        self._counts = Counter()

    def metrics(self):
        with self._lock:
            return {**dict(self._counts), "files": len(self._entries), "estimated_bytes": self._weight,
                    "max_files": self.max_files, "max_bytes": self.max_bytes,
                    "index_files": len(self._index), "index_estimated_bytes": self._index_weight,
                    "max_index_files": self.max_index, "max_index_bytes": self.index_bytes}

    def _count(self, key, value=1):
        with self._lock:self._counts[key] += value

    def _drop(self, key):
        entry = self._entries.pop(key, None)
        if entry is not None:self._weight -= entry.document.weight
        entry = self._index.pop(key, None)
        if entry is not None:self._index_weight -= entry.document.weight

    def invalidate(self, path):
        key = canonical(path)
        with self._lock:
            self._drop(key)
            if any(flight[0] == key for flight in self._flights):
                self._generations[key] = self._generations.get(key, 0) + 1
            else:self._generations.pop(key, None)
            self._counts["invalidations"] += 1

    def clear(self):
        with self._lock:
            self._entries.clear();self._index.clear();self._generations.clear()
            self._totals.clear()
            self._weight = self._index_weight = 0;self._epoch += 1
            self._counts["clears"] += 1

    def prune(self, directory, paths):
        parent, seen = canonical(directory), {canonical(path) for path in paths}
        with self._lock:
            for key in tuple(self._index.keys() | self._entries.keys()):
                if os.path.dirname(key) == parent and key not in seen:
                    self.invalidate(key)
                    self._counts["removed_files"] += 1

    def directory_result(self, directory, results):
        """Adjust only changed files' cents/counts; errors stay explicit."""
        key = canonical(directory)
        current = {}
        for path, (result, _) in results.items():
            ok = result.status == "ok"
            current[canonical(path)] = (result.source_sha256, int(ok), int(result.status == "error"),
                int(result.status == "unsupported"), result.totals.income_cents if ok else 0,
                result.totals.cost_cents if ok else 0)
        with self._lock:
            old, values = self._totals.get(key, ({}, (0, 0, 0, 0, 0)))
            values = list(values)
            changed = 0
            for path in old.keys() | current.keys():
                before, after = old.get(path), current.get(path)
                if before == after:continue
                changed += 1
                for sign, entry in ((-1, before), (1, after)):
                    if entry is not None:
                        values = [total + sign * value for total, value in zip(values, entry[1:])]
            if len(current) <= self.max_index:self._totals[key] = (current, tuple(values))
            else:self._totals.pop(key, None)
            self._counts["aggregate_changed_files"] += changed
        valid, errors, unsupported, income, cost = values
        return Scan(results, {"valid_files": valid, "errors": errors, "unsupported": unsupported,
            "income_cents": income, "cost_cents": cost, "profit_cents": income - cost,
            "status": "partial" if errors or unsupported else "ok", "changed_files": changed})

    def _put(self, key, version, document):
        full = self._entries.get(key)
        self._drop(key)
        summary = document.summary()
        if self.max_index > 0 and summary.weight <= self.index_bytes:
            self._index[key] = Entry(version, summary, PARSER_VERSION);self._index_weight += summary.weight
            while len(self._index) > self.max_index or self._index_weight > self.index_bytes:
                _, entry = self._index.popitem(last=False);self._index_weight -= entry.document.weight
                self._counts["index_evictions"] += 1
        if document.projection == "summary":
            if full and full.parser_version == PARSER_VERSION and full.document.result.source_sha256 == document.result.source_sha256:
                document = full.document
            else:return
        if self.max_files <= 0 or document.weight > self.max_bytes:
            self._counts["uncached_large_files"] += 1
            return
        self._entries[key] = Entry(version, document, PARSER_VERSION);self._weight += document.weight
        while len(self._entries) > self.max_files or self._weight > self.max_bytes:
            _, entry = self._entries.popitem(last=False);self._weight -= entry.document.weight
            self._counts["evictions"] += 1

    def get(self, path, context, *, detail=True):
        key = canonical(path)
        for attempt in range(3):
            context.check()
            try:
                version = file_version(path);self._count("metadata_probes")
                self._count("version_backend:" + version.backend)
            except OSError as exc:
                self.invalidate(key);self._count("unavailable_files")
                return failed_document(exc)
            context.check()
            with self._lock:
                generation = (self._epoch, self._generations.get(key, 0), PARSER_VERSION)
                entries = self._entries if detail else self._index
                old = entries.get(key)
                if old and old.parser_version == PARSER_VERSION and old.version == version and version.strong:
                    entries.move_to_end(key);self._counts["hits"] += 1
                    return old.document
                flight_key = (key, version, generation)
                event = self._flights.get(flight_key)
                leader = event is None
                if leader:self._flights[flight_key] = event = Event()
            if not leader:
                self._count("coalesced_waits")
                while not event.wait(.05):context.check()
                continue
            try:
                self._count("source_reads")
                raw = read_bytes(path)
                self._count("source_bytes", len(raw) if raw is not None else 0)
                if old and not version.strong:
                    self._count("weak_hash_probes")
                if old and old.parser_version == PARSER_VERSION and old.document.result.source_sha256 == digest(raw):
                    document = old.document;self._count("verified_hits")
                else:
                    self._count("misses")
                    document = parse_document(raw)
                    self._count("workbook_opens", document.workbook_opens)
                    self._count("formula_cache_opens", document.formula_cache_opens)
                after = file_version(path);self._count("metadata_probes")
                context.check()
                with self._lock:
                    current = (self._epoch, self._generations.get(key, 0), PARSER_VERSION)
                    if generation != current or version != after:
                        self._counts["discarded_changes"] += 1
                        continue
                    self._put(key, after, document)
                return document if detail else document.summary()
            except OSError as exc:
                self.invalidate(key)
                return failed_document(exc)
            finally:
                with self._lock:
                    self._flights.pop(flight_key, None)
                    if not any(flight[0] == key for flight in self._flights):self._generations.pop(key, None)
                event.set()
        self.invalidate(key)
        return failed_document(OSError("文件持续变化，未使用旧缓存；请重新刷新"))
