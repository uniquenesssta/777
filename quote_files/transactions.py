"""Cooperating writers: native lock, checked preimage, backup and atomic publish.

Windows uses a nonblocking CRT byte lock on a persistent adjacent lock file.
The POSIX backend exists only for auxiliary synthetic checks. Never delete a
lock file or infer ownership from its age. External editors do not participate.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import uuid

FILE_LIMIT = 20 * 1024 * 1024
UNSPECIFIED = object()


class FileFailure(Exception):
    def __init__(self, message, *, request_id=None, diagnostic=None):
        super().__init__(message)
        self.request_id, self.diagnostic = request_id, diagnostic


class FileBusy(FileFailure):
    pass


class FileConflict(FileFailure):
    pass


class UnknownCommit(FileFailure):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def checked_leaf(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise FileFailure("拒绝链接/重解析文件；请使用明确的普通文件路径")
    if not stat.S_ISREG(info.st_mode):
        raise FileFailure("目标不是普通文件")


def read_bytes(path):
    checked_leaf(path)
    try:
        with open(path, "rb") as stream:
            raw = stream.read(FILE_LIMIT + 1)
    except FileNotFoundError:
        return None
    if len(raw) > FILE_LIMIT:
        raise FileFailure("文件超过20MiB过渡期写入上限；原件只读保留")
    return raw


@contextmanager
def file_lock(path):
    path = Path(path)
    lock = path.with_name("." + path.name + ".777.lock")
    checked_leaf(lock)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), 0o600)
    acquired = False
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as error:
            raise FileBusy("文件正在由其他写端处理；本次未提交，请稍后重试。") from error
        owner = {"host": socket.gethostname(), "pid": os.getpid(), "token": str(uuid.uuid4()),
                 "acquired_at": datetime.now(timezone.utc).isoformat()}
        os.write(fd, b"#" + json.dumps(owner).encode("utf-8"))
        os.ftruncate(fd, os.lseek(fd, 0, os.SEEK_CUR))
        yield
    finally:
        if acquired:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                # Closing the handle owns release; an unlock diagnostic must not
                # turn a verified committed transaction into "not saved".
                pass
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass  # Do not replace a verified commit/failure with cleanup.
        else:
            os.close(fd)


def write_exclusive(path, raw):
    with open(path, "xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def journal_path(path, request_id):
    if str(uuid.UUID(request_id)) != request_id:
        raise FileFailure("请求编号格式无效")
    return Path(path).parent / ".777-recovery" / (Path(path).name + "." + request_id + ".json")


def write_journal(path, record):
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    write_exclusive(temp, json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"))
    os.replace(temp, path)


@dataclass(frozen=True)
class CommitResult:
    path: str
    request_id: str
    result: dict
    already_committed: bool
    content_sha256: str
    diagnostic: str | None = None


def query_request(path, request_id, inspect):
    """No writes or lock acquisition; absence alone never proves non-commit."""
    raw = read_bytes(path)
    found = inspect(raw, request_id) if raw is not None else None
    if found is not None:
        return {"status": "committed", "result": found, "content_sha256": digest(raw)}
    journal = journal_path(path, request_id)
    if not journal.exists():
        return {"status": "not_found", "reason": "没有请求回执，不能据此推断是否提交"}
    state = json.loads(journal.read_text(encoding="utf-8"))
    if digest(raw) == state["after_sha256"]:
        return {"status": "committed", "result": state["result"], "content_sha256": digest(raw)}
    if digest(raw) == state["before_sha256"]:
        return {"status": "not_committed", "diagnostic": str(journal)}
    return {"status": "unknown", "diagnostic": str(journal)}


def transact(path, request_id, fingerprint, operation, transform, inspect, *, expected_hash=UNSPECIFIED):
    """transform(raw) -> (validated new bytes, receipt); inspect(bytes,id) -> receipt.

    The receipt MUST contain the request's fingerprint. Idempotent retries are
    resolved before revision checks. A replace exception is queried, never blindly
    retried; prepared copies/backups stay available for explicit recovery.
    """
    path = Path(path)
    journal = journal_path(path, request_id)
    with file_lock(path):
        before = read_bytes(path)
        existing = inspect(before, request_id) if before is not None else None
        if existing is not None:
            if existing.get("fingerprint") != fingerprint:
                raise FileConflict("同一请求编号不能用于不同内容", request_id=request_id)
            return CommitResult(str(path), request_id, existing, True, digest(before))
        if expected_hash is not UNSPECIFIED and digest(before) != expected_hash:
            raise FileConflict("文件已被其他写端修改；请刷新后再操作", request_id=request_id)
        journal.parent.mkdir(exist_ok=True)
        # Resolve crash/unknown journals for this file before allowing new writes.
        for entry in journal.parent.glob(path.name + ".*.json"):
            state = json.loads(entry.read_text(encoding="utf-8"))
            if state.get("state") != "prepared":
                continue
            prior = inspect(before, state["request_id"]) if before is not None else None
            if (prior and prior.get("fingerprint") == state["fingerprint"]) or digest(before) == state["after_sha256"]:
                state["state"] = "committed"
                write_journal(entry, state)
            elif digest(before) != state["before_sha256"]:
                raise UnknownCommit("存在结果不明的写入，请按请求编号核查后继续", request_id=state["request_id"], diagnostic=str(entry))
            else:
                state["state"] = "not_committed"
                write_journal(entry, state)
        if journal.exists():
            previous = json.loads(journal.read_text(encoding="utf-8"))
            if previous["fingerprint"] != fingerprint or previous["operation"] != operation:
                raise FileConflict("恢复请求的内容或操作不一致", request_id=request_id)
        staged = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
        backup = journal.parent / (path.name + "." + uuid.uuid4().hex + ".bak") if before is not None else None
        publishing = False
        try:
            new, receipt = transform(before)
            if len(new) > FILE_LIMIT or receipt.get("fingerprint") != fingerprint:
                raise FileFailure("候选文件过大或回执不一致")
            if inspect(new, request_id) != receipt:
                raise FileFailure("临时文件回读校验失败")
            write_exclusive(staged, new)
            if read_bytes(staged) != new:
                raise FileFailure("临时文件字节校验失败")
            if backup is not None:
                write_exclusive(backup, before)
                if read_bytes(backup) != before:
                    raise FileFailure("写前恢复副本校验失败")
            state = {"protocol": "777-file-v1", "state": "prepared", "request_id": request_id,
                     "operation": operation, "fingerprint": fingerprint, "target": path.name,
                     "before_sha256": digest(before), "after_sha256": digest(new),
                     "staged": staged.name, "backup": backup.name if backup else None, "result": receipt}
            write_journal(journal, state)
            if digest(read_bytes(path)) != digest(before):
                state["state"] = "conflict"
                write_journal(journal, state)
                raise FileConflict("检测到外部修改；原件未被替换，请刷新", request_id=request_id, diagnostic=str(journal))
            publishing = True
            os.replace(staged, path)
            if digest(read_bytes(path)) != digest(new):
                raise UnknownCommit("替换后内容无法确认", request_id=request_id, diagnostic=str(journal))
            state["state"] = "committed"
            try:
                write_journal(journal, state)
            except OSError:
                # Authoritative receipt is already inside the committed file.
                return CommitResult(str(path), request_id, receipt, False, digest(new), str(journal))
            return CommitResult(str(path), request_id, receipt, False, digest(new))
        except (FileConflict, UnknownCommit):
            raise
        except Exception as error:
            if publishing:
                try:
                    observed = read_bytes(path)
                    found = inspect(observed, request_id)
                except Exception:
                    found = None
                if found and found.get("fingerprint") == fingerprint:
                    return CommitResult(str(path), request_id, found, False, digest(observed), str(journal))
                raise UnknownCommit("替换调用结果不明；请查询该请求，不要另建一单重试", request_id=request_id, diagnostic=str(journal)) from error
            raise FileFailure(f"提交前失败，原件未替换：{error}", request_id=request_id, diagnostic=str(staged)) from error
