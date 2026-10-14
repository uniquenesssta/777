"""Regression for main HWND selection, natural exit and retained close failures."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import p07_desktop_check as desktop
from p07_native_window import Windows, close_window, main_window


def window(hwnd, **changes):
    return {**dict(hwnd=hwnd, pid=123, title='记账器', class_name='main', visible=True,
                   width=1440, height=884), **changes}


class SimulatedWindows:
    def __init__(self, entries):
        self.entries, self.posted = entries, []

    def owned(self, pid):
        return self.entries

    def post_close(self, hwnd):
        self.posted.append(hwnd)


class NativeWindowTests(unittest.TestCase):
    def test_only_visible_owned_main_is_selected_even_when_helper_is_marked_visible(self):
        entries = [window(1, title='', class_name='Tao Thread Event Target', width=0, height=0),
                   window(2, pid=456), window(3, visible=False), window(4, title='other'), window(5)]
        self.assertEqual(main_window(entries, 123, '记账器')['hwnd'], 5)
        for invalid in [entries[:-1], [window(5), window(6)],
                        [window(1, class_name='Tao Thread Event Target')]]:
            with self.assertRaisesRegex(RuntimeError, 'MAIN_WINDOW_NOT_UNIQUE'):
                main_window(invalid, 123, '记账器')

    def test_close_posts_once_to_main_and_requires_natural_zero_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            process = unittest.mock.Mock(pid=123)
            process.poll.return_value, process.wait.return_value = None, 0
            api = SimulatedWindows([window(1, title='', class_name='Tao Thread Event Target'), window(5)])
            result = close_window(process, '记账器', Path(folder) / 'close.json', windows=api)
            self.assertEqual(api.posted, [5])
            process.wait.assert_called_once_with(timeout=30)
            self.assertTrue(result['process_exit_observed'])
            self.assertFalse(result['forced_termination'])
            self.assertEqual(result['status'], 'passed')

    def test_missing_ambiguous_and_reused_handles_never_receive_close(self):
        with tempfile.TemporaryDirectory() as folder:
            for entries in [[], [window(1), window(2)]]:
                process, api = unittest.mock.Mock(pid=123), SimulatedWindows(entries)
                process.poll.return_value = None
                with self.assertRaisesRegex(RuntimeError, 'NOT_UNIQUE'):
                    close_window(process, '记账器', Path(folder) / 'close.json', windows=api)
                self.assertEqual(api.posted, [])
                process.wait.assert_not_called()
            api = SimulatedWindows([])
            with patch.object(api, 'owned', side_effect=[[window(1)], [window(2)], []]):
                with self.assertRaisesRegex(RuntimeError, 'WINDOW_CHANGED'):
                    close_window(process, '记账器', Path(folder) / 'close.json', windows=api)
            self.assertEqual(api.posted, [])

    def test_timeout_nonzero_exit_and_post_failure_keep_distinct_diagnostics(self):
        with tempfile.TemporaryDirectory() as folder:
            for kind in ['timeout', 'nonzero', 'post_failed', 'already_exited']:
                with self.subTest(kind=kind):
                    path, api, process = Path(folder) / 'close.json', SimulatedWindows([window(5)]), unittest.mock.Mock(pid=123)
                    process.poll.return_value, process.wait.return_value = None, 0
                    if kind == 'timeout':
                        process.wait.side_effect = subprocess.TimeoutExpired(['owned'], 30)
                    elif kind == 'nonzero':
                        process.wait.return_value = 7
                    elif kind == 'post_failed':
                        api.post_close = unittest.mock.Mock(side_effect=OSError('post denied'))
                    else:
                        process.poll.return_value = 0
                    with self.assertRaises((RuntimeError, OSError)):
                        close_window(process, '记账器', path, windows=api)
                    record = json.loads(path.read_text(encoding='utf-8'))
                    self.assertEqual(record['status'], 'failed')
                    self.assertFalse(record['forced_termination'])
                    self.assertEqual(record['close_message_posted'], kind in ['timeout', 'nonzero'])
                    self.assertEqual(record['process_exit_observed'], kind == 'nonzero')
                    process.kill.assert_not_called()

    def test_child_holding_output_open_does_not_delay_parent_exit_with_file_log(self):
        with tempfile.TemporaryDirectory() as folder:
            ready, release = Path(folder) / 'ready', Path(folder) / 'release'
            child = "from pathlib import Path;import sys,time;Path(sys.argv[1]).touch()\nwhile not Path(sys.argv[2]).exists():time.sleep(.01)"
            parent = "import subprocess,sys;subprocess.Popen([sys.executable,'-c',*sys.argv[1:]]);print('parent exited',flush=True)"
            with (Path(folder) / 'process.log').open('wb') as log:
                process = subprocess.Popen([sys.executable, '-c', parent, child, str(ready), str(release)], stdout=log, stderr=subprocess.STDOUT)
                try:
                    self.assertEqual(process.wait(timeout=5), 0)
                    deadline = time.monotonic() + 5
                    while not ready.exists() and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue(ready.exists())
                    self.assertFalse(release.exists())  # Descendant still owns its output handle.
                finally:
                    release.touch()
                    process.wait(timeout=5)
            # Allow descendant file handles to close before TemporaryDirectory cleanup on Windows.
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    (Path(folder) / 'process.log').unlink()
                    break
                except PermissionError:
                    time.sleep(.02)

    def test_old_pipe_communicate_can_time_out_after_parent_already_exited(self):
        with tempfile.TemporaryDirectory() as folder:
            release = Path(folder) / 'release'
            child = "from pathlib import Path;import sys,time\nwhile not Path(sys.argv[1]).exists():time.sleep(.01)"
            parent = "import subprocess,sys;subprocess.Popen([sys.executable,'-c',*sys.argv[1:]])"
            process = subprocess.Popen([sys.executable, '-c', parent, child, str(release)],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            try:
                self.assertEqual(process.wait(timeout=5), 0)
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.communicate(timeout=.2)
                self.assertEqual(process.poll(), 0)
            finally:
                release.touch()
                process.communicate(timeout=5)

    def test_main_retains_completed_interactions_when_later_close_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            for filename, value in [('native-webview.json', {'status': 'passed', 'manager_submit': True}),
                                    ('native-window-close.json', {'status': 'failed', 'close_message_posted': True})]:
                (output / filename).write_text(json.dumps(value), encoding='utf-8')
            with redirect_stdout(io.StringIO()), patch.object(desktop, 'new_output', return_value=output), \
                    patch.object(desktop, 'fingerprints', return_value={}), \
                    patch.object(desktop, 'preflight', side_effect=RuntimeError('simulated failure')):
                self.assertEqual(desktop.main(['--preflight', '--output', folder]), 1)
            report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['native_window_interactions']['status'], 'passed')
            self.assertEqual(report['native_window_close']['status'], 'failed')
            self.assertIsNone(report['native_window'])

    @unittest.skipUnless(os.name == 'nt', 'requires real Win32 windows; not native Tauri acceptance')
    def test_real_win32_main_closes_while_visible_event_helper_is_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            ready = Path(folder) / 'ready.json'
            with (Path(folder) / 'fixture.log').open('wb') as log:
                process = subprocess.Popen([sys.executable, str(ROOT / 'tests/p07_window_fixture.py'), str(ready)],
                                           stdout=log, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 10
                    while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue(ready.exists())
                    handles = json.loads(ready.read_text(encoding='utf-8'))
                    result = close_window(process, '记账器', Path(folder) / 'close.json', windows=Windows())
                    self.assertEqual(result['target']['hwnd'], handles['main'])
                    helper = next(w for w in result['windows_before'] if w['hwnd'] == handles['helper'])
                    self.assertTrue(helper['visible'])
                    self.assertEqual(helper['class_name'], 'Tao Thread Event Target')
                    self.assertEqual(result['exit_code'], 0)  # Child also verifies helper survived the close.
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
