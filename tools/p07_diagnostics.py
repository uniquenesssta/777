"""Bounded operational logging; never serialize control payloads or subprocess arguments."""
import atexit
import json
import logging
from datetime import datetime, timezone, timedelta
import uuid
import os
from pathlib import Path
import threading
import time

_LOCK = threading.RLock()
_LOGGER = None
_RECENT = {}
_ROOT = Path(__file__).resolve().parents[1]

class SessionFileHandler(logging.Handler):
    """One cross-process lock and rotation convention shared with Rust fs2."""
    def __init__(self, directory, limit=4*1024*1024):
        super().__init__()
        self.directory = directory
        self.limit = limit
        self.warned = False

    def emit(self, record):
        try:
            raw = (self.format(record) + '\n').encode('utf-8')
            if len(raw) > 16384:
                return
            with open(self.directory / 'runtime.lock', 'a+b') as lock:
                deadline = time.monotonic() + .1
                while True:
                    try:
                        if os.name == 'nt':
                            import msvcrt
                            lock.seek(0)
                            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.monotonic() >= deadline: raise
                        time.sleep(.002)
                try:
                    path = self.directory / 'runtime.jsonl'
                    if (path.stat().st_size if path.exists() else 0) + len(raw) > self.limit:
                        (self.directory / 'runtime.4.jsonl').unlink(missing_ok=True)
                        for i in range(3, 0, -1):
                            previous = self.directory / f'runtime.{i}.jsonl'
                            if previous.exists(): previous.replace(self.directory / f'runtime.{i+1}.jsonl')
                        if path.exists(): path.replace(self.directory / 'runtime.1.jsonl')
                    with path.open('ab') as stream:
                        stream.write(raw)
                        stream.flush()
                finally:
                    if os.name == 'nt':
                        lock.seek(0)
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except OSError:
            if not self.warned:
                self.warned = True
                print('LOG_WRITE_FAILED: ' + str(self.directory))

def initialize(root=None):
    global _LOGGER
    with _LOCK:
        if _LOGGER is not None:
            return
        root = Path(root or _ROOT)
        os.environ['QUOTE777_LOG_ROOT'] = str(root)
        try:
            session = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d_%H%M%S') + '_' + uuid.uuid4().hex[:12]
            directory = root / 'logs' / session
            directory.mkdir(parents=True, exist_ok=False)
            os.environ['QUOTE777_LOG_SESSION'] = session
            logger = logging.getLogger('quote777.development')
            logger.propagate = False
            logger.setLevel(logging.INFO)
            handler = SessionFileHandler(directory)
            handler.setFormatter(logging.Formatter('%(message)s'))
            logger.addHandler(handler)
            _LOGGER = logger
        except OSError:
            _LOGGER = False
            print('LOG_WRITE_FAILED: ' + str(root / 'logs'))
    event('runtime.start', os=os.name, account=os.environ.get('USERNAME', os.environ.get('USER', 'unknown')))
    atexit.register(lambda: event('runtime.stop'))

def _write(name, fields):
    _LOGGER.info(json.dumps(dict(time_unix_ms=int(time.time()*1000), pid=os.getpid(), component='development', session=os.environ.get('QUOTE777_LOG_SESSION'), event=name, fields=fields), ensure_ascii=False))

def event(name, **fields):
    if _LOGGER is None:
        initialize()
    if not _LOGGER:
        return
    with _LOCK:
        now = time.monotonic()
        key = json.dumps([name, fields], sort_keys=True, ensure_ascii=False)
        if len(key) > 12000:
            fields = {'detail': 'OVERSIZED_DIAGNOSTIC_OMITTED'}
            key = name
        old = _RECENT.get(key)
        if old and now-old[0] < 60:
            old[1] += 1
            return
        for item, (since, count) in list(_RECENT.items()):
            if count and (now-since >= 60 or name == 'runtime.stop'):
                _write('repeated.summary', dict(event=item, suppressed=count))
                del _RECENT[item]
        if len(_RECENT) >= 256:
            _RECENT.clear()
        _RECENT[key] = [now, 0]
        _write(name, fields)

def failure(operation, error):
    # Exception text can contain subprocess arguments/secrets. Only OS errors and
    # recognized application codes are allowed; no traceback locals or payloads.
    import re
    fields = dict(operation=operation, exception=type(error).__name__)
    if isinstance(error, OSError):
        fields.update(errno=error.errno, winerror=getattr(error, 'winerror', None),
                      path=error.filename, target=error.filename2, message=error.strerror)
    elif re.fullmatch(r'[A-Z][A-Z0-9_]{1,100}', str(error)):
        fields['code'] = str(error)
    if hasattr(error, 'returncode'):fields['returncode'] = error.returncode
    if hasattr(error, 'timeout'):fields['timeout_seconds'] = error.timeout
    event('operation.error', **fields)
