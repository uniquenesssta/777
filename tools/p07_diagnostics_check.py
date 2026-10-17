"""Actual host failure must retain OS detail on disk without changing CLI protocol."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
def main(binary=None):
    binary = binary or ROOT / 'target/release' / ('quote-host.exe' if os.name == 'nt' else 'quote-host')
    with tempfile.TemporaryDirectory(prefix='777-diagnostics-') as tmp:
        root = Path(tmp)
        missing = root / '不存在的目录' / 'host'
        command = [str(binary), 'inspect', '--root', str(missing)]
        if os.name != 'nt':command.append('--auxiliary')
        result = subprocess.run(command, env=dict(os.environ, QUOTE777_LOG_ROOT=str(root)), capture_output=True, timeout=30)
        assert result.returncode == 1, result.returncode
        response = json.loads(result.stderr.decode('utf-8').splitlines()[-1])
        assert response['status'] == 'failed'
        rows = [json.loads(line) for line in (root / 'logs/host.jsonl').read_text(encoding='utf-8').splitlines()]
        errors = [r['fields'] for r in rows if r['event'] == 'filesystem.error']
        assert any(e.get('os_code') is not None and e.get('path') and str(missing) in e['path'] for e in errors), errors
        assert rows[0]['event'] == 'runtime.start'
        assert rows[-1]['event'] == 'runtime.stop'
        print(json.dumps({'status':'passed','actual_os':os.name,'cli_failure_preserved':True,'os_error_and_path_logged':True,'lifecycle_logged':True}))
if __name__ == '__main__':main()
