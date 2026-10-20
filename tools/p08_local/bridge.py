"""Line IPC to the actual Rust desktop parser, no Python business implementation."""
import json
import queue
import subprocess
import threading


class Bridge:
    def __init__(self, binary, profile, package, *, worker=False):
        args = [str(binary), '--verification-bridge', '--profile', str(profile), '--package', str(package)]
        if worker:
            args.append('--offline-worker')
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.rows = queue.Queue()
        def consume():
            for line in self.process.stdout:
                self.rows.put(line)
            self.rows.put(None)
        threading.Thread(target=consume, daemon=True).start()

    def call(self, action, **fields):
        self.process.stdin.write(json.dumps(dict(action=action, **fields), ensure_ascii=False) + '\n')
        self.process.stdin.flush()
        value = self.rows.get(timeout=40)
        if value is None:
            raise RuntimeError('Native IPC exited: ' + self.process.stderr.read()[-700:])
        value = json.loads(value)
        if 'error' in value:
            raise RuntimeError('Native IPC rejected '+action+': '+value['error']['code'])
        return value['ok']

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=10)
