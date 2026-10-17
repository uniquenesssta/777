"""Bounded operational logging; never serialize control payloads or subprocess arguments."""
import atexit
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import threading
import time

_LOCK = threading.RLock()
_LOGGER = None
_RECENT = {}
_ROOT = Path(__file__).resolve().parents[1]

def initialize(root=None):
    global _LOGGER
    with _LOCK:
        if _LOGGER is not None:
            return
        root = Path(root or _ROOT)
        os.environ['QUOTE777_LOG_ROOT'] = str(root)
        try:
            directory = root / 'logs'
            directory.mkdir(exist_ok=True)
            logger = logging.getLogger('quote777.development')
            logger.propagate = False
            logger.setLevel(logging.INFO)
            handler = RotatingFileHandler(directory / 'development.jsonl', maxBytes=4*1024*1024, backupCount=4, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(message)s'))
            logger.addHandler(handler)
            _LOGGER = logger
        except OSError:
            _LOGGER = False
            print('LOG_WRITE_FAILED: ' + str(root / 'logs'))
    event('runtime.start', os=os.name, account=os.environ.get('USERNAME', os.environ.get('USER', 'unknown')))
    atexit.register(lambda: event('runtime.stop'))

def _write(name, fields):
    _LOGGER.info(json.dumps(dict(time_unix_ms=int(time.time()*1000), pid=os.getpid(), component='development', event=name, fields=fields), ensure_ascii=False))

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
