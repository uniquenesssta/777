"""One bounded file with two rotated copies, shared with native/PowerShell locking."""
import logging,os,time
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
                        (self.directory / 'runtime.2.jsonl').unlink(missing_ok=True)
                        for i in range(1, 0, -1):
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

