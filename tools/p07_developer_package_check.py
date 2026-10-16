"""Run the initial installer build through the actual developer window in an owned fixture."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from types import SimpleNamespace
from p07_developer import Developer
from p07_dev_host import command, stop_host
from p07_native_window import Windows, close_window


def package_from_window(host, root, delivery, version, release):
    evidence = release.parent / 'developer-ui'
    evidence.mkdir()
    devdir = host.root / 'developer'; devdir.mkdir()
    controller = Developer(SimpleNamespace(ROOT=root, DEV=devdir, PORT=host.port, command=command, stop_host=stop_host), host.host_root, host.process)
    host.process = None
    controller.user, controller.password = 'manager', host.password
    controller.remember(host.host_root, 'manager', host.password)
    profile = host.root / 'desktop'
    connection = controller.connection()
    (profile / 'bootstrap.json').write_text(json.dumps(dict(schema='777-desktop-bootstrap-v1', delivery='development', connection=connection, username='manager', password=host.password)), encoding='utf-8')
    controller.serve()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
    process = None
    try:
        with (evidence / 'process.log').open('wb') as log:
            process = subprocess.Popen([str(root / 'target/debug/quote-desktop.exe'), '--verification-window', '--profile', str(profile), '--debug-port', str(port)], stdout=log, stderr=subprocess.STDOUT)
            result = subprocess.run([shutil.which('node'), str(root / 'desktop/tests/windows-developer.mjs'), str(port), str(evidence), delivery, version, str(devdir / 'packages')], cwd=root / 'desktop', timeout=2500)
            if result.returncode:raise RuntimeError('DEVELOPER_WINDOW_PACKAGE_FAILED')
            job = json.loads((evidence / 'developer-job.json').read_text(encoding='utf-8'))
            shutil.copytree(job['output'], release)
            close_window(process, '记账器', evidence / 'developer-close.json', windows=Windows())
            process = None
    finally:
        if process and process.poll() is None:
            from p07_check_runner import stop_tree
            stop_tree(process)
        # The original fixture continues the install/enrollment/upgrade checks.
        host.process = controller.process; controller.process = None
        controller.close()
        for key in ['QUOTE777_DEVELOPER_PORT','QUOTE777_DEVELOPER_TOKEN']:os.environ.pop(key,None)
