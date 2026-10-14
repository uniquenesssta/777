"""Real child-process checks for P07 progress, resource bounds and safe interruption."""
from concurrent.futures import ThreadPoolExecutor
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
import p07_check_runner as runner
import p07_desktop_check as desktop


class RunnerTests(unittest.TestCase):
    def test_node22_dependency_floor_accepts_22_12_and_newer_without_requiring_24(self):
        for version in ['v22.12.0', 'v22.12.1', 'v22.22.0', 'v24.19.0']:
            with self.subTest(version=version):
                self.assertTrue(runner.node_supported(version))
        for version in ['v20.19.0', 'v22.0.0', 'v22.11.9', 'invalid']:
            with self.subTest(version=version):
                self.assertFalse(runner.node_supported(version))

    def progress(self, folder, jobs=1):
        return runner.Progress(folder, {'status': 'running', 'commands': []}, jobs, io.StringIO())

    def test_native_plan_only_builds_required_release_programs_and_full_gate_stays_in_ci(self):
        paths = {'cargo': 'cargo', 'npm': 'npm'}
        native = [c for _, c in runner.build_plan(paths, False, 1)]
        self.assertFalse(any('clippy' in c or 'test' in c for c in native))
        release = [c for c in native if 'build' in c and '--release' in c][0]
        self.assertEqual(set(release[release.index('--features') + 1].split(',')),
                         {'quote-desktop/verification', 'quote-desktop/custom-protocol'})
        full = [c for _, c in runner.build_plan(paths, True, 2)]
        self.assertTrue(any('clippy' in c and '-D' in c and 'warnings' in c for c in full))
        self.assertTrue(any('test' in c and '--test-threads=2' in c for c in full))
        for c in full:
            if c[0] == 'cargo' and any(v in c for v in ['clippy', 'test', 'build']):
                self.assertEqual(c[c.index('-j') + 1], '2')

    def test_actual_release_probe_requires_production_protocol_and_embedded_entry_assets(self):
        good = dict(windows=True, release=True, custom_protocol=True, tauri_is_dev=False,
                    embedded_index=True, entry_js=True, entry_css=True, asset_count=8)
        self.assertIs(runner.require_embedded_frontend(good), good)
        for key in ['windows', 'release', 'custom_protocol', 'embedded_index', 'entry_js', 'entry_css']:
            with self.subTest(rejected=key), self.assertRaisesRegex(RuntimeError, 'RELEASE_EMBEDDED_FRONTEND_REQUIRED'):
                runner.require_embedded_frontend({**good, key: False})
        for broken in [{**good, 'tauri_is_dev': True}, {**good, 'asset_count': 0}, {}, None]:
            with self.assertRaisesRegex(RuntimeError, 'RELEASE_EMBEDDED_FRONTEND_REQUIRED'):
                runner.require_embedded_frontend(broken)

    def test_log_and_progress_are_visible_before_the_child_exits(self):
        with tempfile.TemporaryDirectory() as folder:
            progress = self.progress(folder)
            marker = Path(folder) / 'release-child'
            code = "import time,sys;from pathlib import Path;sys.stdout.buffer.write('实时进度\\r\\n'.encode());sys.stdout.flush()\nwhile not Path(__import__('sys').argv[1]).exists():time.sleep(.02)"
            with ThreadPoolExecutor(max_workers=1) as pool:
                work = pool.submit(progress.run, [sys.executable, '-c', code, str(marker)], timeout=10)
                try:
                    deadline = time.monotonic() + 5
                    while '\n实时进度\n' not in progress.stream.getvalue().replace('\r\n', '\n') and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertIn('\n实时进度\n', progress.stream.getvalue().replace('\r\n', '\n'))
                    self.assertFalse(work.done())
                    checkpoint = json.loads((Path(folder) / 'report.json').read_bytes())
                    self.assertEqual(checkpoint['commands'][0]['status'], 'running')
                    self.assertIn('实时进度', (Path(folder) / 'command-01.log').read_text(encoding='utf-8'))
                finally:
                    marker.touch()
                self.assertEqual(work.result(timeout=5)['exit_code'], 0)

    def test_build_and_test_bounds_override_inherited_high_parallelism(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'CARGO_BUILD_JOBS': '32', 'RUST_TEST_THREADS': '32'}):
            progress = self.progress(folder)
            result = progress.run([sys.executable, '-c', "import os,json;print(json.dumps([os.environ['CARGO_BUILD_JOBS'],os.environ['RUST_TEST_THREADS']]))"])
            self.assertEqual(json.loads(result['stdout']), ['1', '1'])

    def test_timeout_stops_owned_descendants_but_leaves_unrelated_process_alive(self):
        with tempfile.TemporaryDirectory() as folder:
            progress = self.progress(folder)
            owned = Path(folder) / 'owned-finished'
            unrelated = Path(folder) / 'unrelated-finished'
            finish = "import time,sys;from pathlib import Path;time.sleep(2);Path(sys.argv[1]).write_text('finished')"
            other = subprocess.Popen([sys.executable, '-c', finish, str(unrelated)])
            parent = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]);print('owned-child-started',flush=True);time.sleep(30)"
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    progress.run([sys.executable, '-c', parent, finish, str(owned)], timeout=.8)
                other.wait(timeout=10)
                self.assertTrue(unrelated.exists())
                self.assertFalse(owned.exists())
                record = json.loads((Path(folder) / 'report.json').read_bytes())['commands'][0]
                self.assertIn('owned-child-started', record['stdout'])
                self.assertEqual(record['status'], 'timed_out')
                self.assertTrue(record['owned_process_tree_cleanup']['root_exited'])
            finally:
                if other.poll() is None:
                    other.terminate()
                    other.wait(timeout=5)

    def test_keyboard_interrupt_preserves_current_command_and_reaps_its_child(self):
        with tempfile.TemporaryDirectory() as folder:
            progress = self.progress(folder)
            drain = progress._drain
            interrupted = False

            def interrupt_once(reader, decoder):
                nonlocal interrupted
                if not interrupted:
                    interrupted = True
                    raise KeyboardInterrupt
                drain(reader, decoder)

            with patch.object(progress, '_drain', side_effect=interrupt_once):
                with self.assertRaises(KeyboardInterrupt):
                    progress.run([sys.executable, '-c', 'import time;time.sleep(30)'])
            record = json.loads((Path(folder) / 'report.json').read_bytes())['commands'][0]
            self.assertEqual(record['status'], 'interrupted')
            self.assertTrue(record['owned_process_tree_cleanup']['root_exited'])
            self.assertIsNotNone(record['exit_code'])

    def test_missing_environment_fails_before_install_or_build(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runner.shutil, 'which', return_value=None):
            progress = self.progress(folder)
            with self.assertRaisesRegex(RuntimeError, '缺少命令'):
                runner.preflight(progress)
            self.assertEqual(progress.report['commands'], [])

    def test_checkpoint_failure_after_spawn_does_not_leave_a_compiler_running(self):
        with tempfile.TemporaryDirectory() as folder:
            progress = self.progress(folder)
            save = progress.save
            calls = 0

            def fail_after_spawn():
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError('simulated checkpoint write failure')
                save()

            with patch.object(progress, 'save', side_effect=fail_after_spawn):
                with self.assertRaisesRegex(OSError, 'checkpoint write'):
                    progress.run([sys.executable, '-c', 'import time;time.sleep(30)'])
            record = json.loads((Path(folder) / 'report.json').read_bytes())['commands'][0]
            self.assertEqual(record['status'], 'failed')
            self.assertTrue(record['owned_process_tree_cleanup']['root_exited'])
            self.assertIsNotNone(record['exit_code'])

    def test_missing_pinned_toolchain_never_launches_a_compiler_or_automatic_install(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runner.shutil, 'which', side_effect=lambda n: n):
            progress = self.progress(folder)
            with patch.object(runner, 'checked', side_effect=['v24.19.0', '11.9.0', 'stable-x86_64-pc-windows-msvc (default)']) as calls:
                with self.assertRaisesRegex(RuntimeError, '缺少固定 Rust'):
                    runner.preflight(progress)
            commands = [c.args[1] for c in calls.call_args_list]
            self.assertEqual(len(commands), 3)
            self.assertFalse(any('rustc' in c[0] or 'install' in c for c in commands))

    def test_main_saves_an_interrupted_report_without_a_traceback(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()), \
                patch.object(desktop, 'new_output', return_value=Path(folder)), \
                patch.object(desktop, 'fingerprints', return_value={}), \
                patch.object(desktop, 'preflight', side_effect=KeyboardInterrupt):
            self.assertEqual(desktop.main(['--preflight', '--output', folder]), 130)
            report = json.loads((Path(folder) / 'report.json').read_bytes())
            self.assertEqual(report['status'], 'interrupted')
            self.assertFalse(report['production_paths_accessed'])


if __name__ == '__main__':
    unittest.main()
