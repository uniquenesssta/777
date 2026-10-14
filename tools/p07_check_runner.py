"""Visible, bounded P07 checks; never terminate processes outside the owned tree."""
import codecs
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN = '1.97.1'


def node_supported(version):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', version.strip())
    return bool(match and tuple(map(int, match.groups())) >= (22, 12, 0))


def require_embedded_frontend(info):
    required = ['windows', 'release', 'custom_protocol', 'embedded_index', 'entry_js', 'entry_css']
    if (not isinstance(info, dict) or any(info.get(k) is not True for k in required)
            or info.get('tauri_is_dev') is not False or not isinstance(info.get('asset_count'), int)
            or info['asset_count'] < 3):
        raise RuntimeError('RELEASE_EMBEDDED_FRONTEND_REQUIRED: release exe must contain index/JS/CSS and use the Tauri production protocol')
    return info


class Progress:
    def __init__(self, output, report, jobs=1, stream=None):
        self.output = Path(output)
        self.report = report
        self.jobs = jobs
        self.stream = stream if stream is not None else sys.stdout

    def emit(self, value):
        try:
            self.stream.write(value)
        except UnicodeEncodeError:
            self.stream.write(value.encode(self.stream.encoding, 'replace').decode(self.stream.encoding))
        self.stream.flush()

    def save(self):
        path = self.output / 'report.json'
        pending = self.output / 'report.tmp'
        pending.write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        pending.replace(path)

    def stage(self, label):
        self.report['current_step'] = label
        self.save()
        self.emit('\n>>> ' + label + '\n')

    def _drain(self, reader, decoder):
        while chunk := reader.read(65536):
            self.emit(decoder.decode(chunk))

    def run(self, command, timeout=1800, label=None):
        command = [str(v) for v in command]
        label = label or Path(command[0]).name
        index = len(self.report['commands']) + 1
        log = self.output / f'command-{index:02d}.log'
        record = dict(command=command, label=label, status='running', log=log.name,
                      output_streams='stdout and stderr merged in live log', exit_code=None)
        self.report['commands'].append(record)
        self.stage(label)
        self.emit('  ' + subprocess.list2cmdline(command) + '\n')
        start = time.monotonic()
        process = None
        env = dict(os.environ, PYTHONIOENCODING='utf-8', CARGO_BUILD_JOBS=str(self.jobs),
                   RUST_TEST_THREADS=str(self.jobs), CARGO_TERM_COLOR='never')
        options = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP |
                    subprocess.BELOW_NORMAL_PRIORITY_CLASS} if os.name == 'nt'
                   else {'start_new_session': True})
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        try:
            # Files avoid the Windows pipe-reader join seen in the interrupted old runner.
            with log.open('wb') as writer, log.open('rb') as reader:
                process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                           stdout=writer, stderr=subprocess.STDOUT, **options)
                record['pid'] = process.pid
                self.save()
                heartbeat = start
                try:
                    while process.poll() is None:
                        self._drain(reader, decoder)
                        now = time.monotonic()
                        if now - start > timeout:
                            raise subprocess.TimeoutExpired(command, timeout)
                        if now - heartbeat >= 20:
                            self.emit(f'  [{label}] 已运行 {int(now-start)} 秒；日志：{log.name}\n')
                            heartbeat = now
                        try:
                            process.wait(timeout=0.2)
                        except subprocess.TimeoutExpired:
                            pass
                except (KeyboardInterrupt, subprocess.TimeoutExpired):
                    record['status'] = 'interrupted' if sys.exc_info()[0] is KeyboardInterrupt else 'timed_out'
                    record['owned_process_tree_cleanup'] = stop_tree(process)
                    raise
                finally:
                    self._drain(reader, decoder)
                    self.emit(decoder.decode(b'', final=True))
            record['status'] = 'passed' if process.returncode == 0 else 'failed'
            return record
        except BaseException as error:
            if process and process.poll() is None:
                record['owned_process_tree_cleanup'] = stop_tree(process)
            if record['status'] == 'running':
                record['status'] = ('interrupted' if isinstance(error, KeyboardInterrupt)
                                    else 'failed' if process else 'failed_to_start')
            record['error'] = type(error).__name__ + ': ' + str(error)
            raise
        finally:
            record['exit_code'] = process.returncode if process else None
            record['elapsed_seconds'] = time.monotonic() - start
            if log.exists():
                with log.open('rb') as f:
                    raw = f.read(4 * 1024 * 1024 + 1)
                record['stdout'] = raw[:4 * 1024 * 1024].decode('utf-8', 'replace')
                record['stdout_truncated_in_report'] = len(raw) > 4 * 1024 * 1024
            else:
                record['stdout'] = ''
            record['stderr'] = ''
            self.save()
            self.emit(f'<<< {label}: {record["status"]} ({record["elapsed_seconds"]:.1f}s)\n')


def stop_tree(process):
    """Only a child process created by this runner and its descendants are eligible."""
    if process.poll() is not None:
        return {'root_exited': True, 'scope': 'owned child already exited'}
    if os.name == 'nt':
        result = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        process.wait(timeout=15)
        return {'root_exited': process.returncode is not None, 'method': 'taskkill owned PID /T',
                'tree_termination_exit_code': result.returncode}
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    return {'root_exited': process.returncode is not None, 'method': 'owned process group'}


def checked(progress, command, label, timeout=60):
    r = progress.run(command, label=label, timeout=timeout)
    if r['exit_code']:
        raise RuntimeError(label + '失败，请查看 ' + r['log'])
    return r['stdout'].strip()


def windows_prerequisites(native):
    import winreg
    tools = shutil.which('cl.exe') and shutil.which('link.exe')
    vswhere = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    if vswhere.is_file():
        p = subprocess.run([str(vswhere), '-latest', '-products', '*', '-requires',
                            'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
        tools = tools or (p.returncode == 0 and bool(p.stdout.strip()))
    if not tools:
        raise RuntimeError('缺少 MSVC C++ 工具。请在 Visual Studio Installer 安装“使用 C++ 的桌面开发”。')
    sdk = False
    runtime = bool(os.environ.get('WEBVIEW2_BROWSER_EXECUTABLE_FOLDER') and
                   (Path(os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER']) / 'msedgewebview2.exe').is_file())
    for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
        for view in [winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY]:
            try:
                with winreg.OpenKey(hive, r'SOFTWARE\Microsoft\Windows Kits\Installed Roots', 0, winreg.KEY_READ | view) as key:
                    root = Path(winreg.QueryValueEx(key, 'KitsRoot10')[0])
                    sdk = sdk or any((root / 'Include' / v.name / 'um/Windows.h').is_file()
                                     for v in (root / 'Lib').glob('*') if (v / 'um/x64/kernel32.lib').is_file())
            except OSError:
                pass
            try:
                # https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution
                with winreg.OpenKey(hive, r'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 0, winreg.KEY_READ | view) as key:
                    version = winreg.QueryValueEx(key, 'pv')[0]
                    runtime = runtime or bool(version and version != '0.0.0.0')
            except OSError:
                pass
    if not sdk:
        raise RuntimeError('缺少 Windows SDK。请在 Visual Studio Installer 安装 Windows 10/11 SDK。')
    if native and not runtime:
        raise RuntimeError('缺少 WebView2 Runtime，请先安装微软 WebView2 Evergreen Runtime。')
    return dict(MSVC_cpp_tools=True, Windows_SDK=True, WebView2_Runtime=runtime)


def preflight(progress, native=False, full=False):
    progress.stage('环境预检（尚未下载依赖或编译）')
    paths = {name: shutil.which(name) for name in ['node', 'npm', 'cargo', 'rustc', 'rustup']}
    missing = [k for k, v in paths.items() if not v]
    if missing:
        raise RuntimeError('缺少命令：' + ', '.join(missing) + '。需要 Node.js 22.12+、Rust 1.97.1/MSVC；安装后重新打开 PowerShell。')
    node = checked(progress, [paths['node'], '--version'], '检查 Node.js')
    if not node_supported(node):
        raise RuntimeError('需要 Node.js 22.12.0 或更新版本，无需升到 24。当前：' + node)
    checked(progress, [paths['npm'], '--version'], '检查 npm')
    installed = checked(progress, [paths['rustup'], 'toolchain', 'list'], '检查已安装 Rust 工具链')
    # Do not let +toolchain silently bootstrap an absent compiler during a preflight.
    wanted = TOOLCHAIN + ('-x86_64-pc-windows-msvc' if os.name == 'nt' else '-')
    if not any(line.split()[0].startswith(wanted) for line in installed.splitlines() if line.strip()):
        raise RuntimeError('缺少固定 Rust 工具链，请先运行：rustup toolchain install 1.97.1 --profile minimal --component rustfmt,clippy')
    rust = checked(progress, [paths['rustc'], '+' + TOOLCHAIN, '-vV'], '检查 Rust 编译目标')
    if os.name == 'nt' and 'host: x86_64-pc-windows-msvc' not in rust:
        raise RuntimeError('需要 x86_64-pc-windows-msvc 工具链。')
    paths['target'] = next(line.removeprefix('host: ').strip() for line in rust.splitlines() if line.startswith('host: '))
    if full:
        components = checked(progress, [paths['rustup'], 'component', 'list', '--toolchain', TOOLCHAIN, '--installed'], '检查 rustfmt / Clippy')
        if not all(any(line.startswith(name + '-') for line in components.splitlines()) for name in ['rustfmt', 'clippy']):
            raise RuntimeError('缺少检查组件，请运行：rustup component add --toolchain 1.97.1 rustfmt clippy')
    missing_modules = [n for n in ['openpyxl', 'PIL', 'cryptography'] if importlib.util.find_spec(n) is None]
    if missing_modules:
        raise RuntimeError('缺少 Python 验证依赖：' + ', '.join(missing_modules) + '。请运行：py -3 -m pip install -r requirements-baseline.txt -r requirements-service.txt')
    result = dict(status='passed', node=node, rust=rust, cargo_jobs=progress.jobs,
                  dependency_sources='Cargo.toml/Cargo.lock and desktop/package-lock.json; download occurs after preflight',
                  Windows_native_prerequisites=windows_prerequisites(native) if os.name == 'nt' else None)
    progress.report['preflight'] = result
    progress.save()
    return paths


def build_plan(paths, full, jobs):
    cargo, npm = paths['cargo'], paths['npm']
    target_name = paths.get('target') or ('x86_64-pc-windows-msvc' if os.name == 'nt' else None)
    target = ['--target', target_name] if target_name else []
    commands = [
        ('安装锁定前端依赖', [npm, 'ci', '--prefix', 'desktop', '--ignore-scripts', '--no-audit', '--no-fund']),
        ('下载锁定 Rust 依赖（已有缓存会复用）', [cargo, '+' + TOOLCHAIN, 'fetch', '--locked', *target]),
        ('构建前端页面', [npm, '--prefix', 'desktop', 'run', 'build']),
    ]
    if full:
        commands += [
            ('前端状态测试', [npm, '--prefix', 'desktop', 'test']),
            ('Rust 格式检查', [cargo, '+' + TOOLCHAIN, 'fmt', '--all', '--', '--check']),
            ('Rust 严格 Clippy', [cargo, '+' + TOOLCHAIN, 'clippy', '--locked', '-j', str(jobs), '--workspace', '--all-targets', '--features', 'quote-desktop/verification', '--', '-D', 'warnings']),
            ('Rust 工作区测试', [cargo, '+' + TOOLCHAIN, 'test', '--locked', '-j', str(jobs), '--workspace', '--features', 'quote-desktop/verification', '--', '--test-threads=' + str(jobs)]),
        ]
    commands.append(('编译所需 release 程序（首次可能较久）', [cargo, '+' + TOOLCHAIN, 'build', '--release', '--locked', '-j', str(jobs), '-p', 'quote-host', '-p', 'quote-ledger', '-p', 'quote-desktop', '--features', 'quote-desktop/verification,quote-desktop/custom-protocol']))
    return commands
