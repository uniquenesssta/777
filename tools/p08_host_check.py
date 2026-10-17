"""Owned synthetic native HTTPS check of the production supervisor shutdown channel."""
import argparse
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'tools')]
from native_host_fixture import Hosted, BINARY, AUXILIARY, command
from p01_validation import new_output


class SupervisedHost(Hosted):
    def start(self):
        args = [str(BINARY), 'run', '--root', str(self.host_root), '--shutdown-stdin']
        if AUXILIARY:
            args.append('--auxiliary')
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = queue.Queue()
        threading.Thread(target=lambda: output.put(self.process.stdout.readline()), daemon=True).start()
        line = output.get(timeout=20)
        if not line or json.loads(line).get('status') != 'ready':
            raise RuntimeError('SUPERVISED_HOST_NOT_READY')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    output = new_output(parser.parse_args().output)
    host = None
    report = {'task': 'P08-02', 'scope': 'synthetic_native_supervisor_channel', 'status': 'failed',
              'windows': os.name == 'nt', 'windows_task_registration': 'not_executed', 'live_hosts_contacted': False}
    try:
        host = SupervisedHost()
        before = command('inspect', root=host.host_root)
        assert before['shutdown_control'] == 'stdin-v1'
        assert host.client('manager').request('GET', '/v1/capabilities')['protocol'] == '777-service-v1'
        host.stop()
        with socket.socket() as probe:
            assert probe.connect_ex(('127.0.0.1', host.port)) != 0
        assert command('inspect', root=host.host_root)['inventory'] == before['inventory']
        host.start()
        assert host.client('manager').request('GET', '/v1/capabilities')['protocol'] == '777-service-v1'
        host.stop()
        report.update(status='passed', checks=['production_stdin_flag_without_isolated_test', 'pinned_https_login_and_capabilities',
                      'graceful_stop_closes_port_preserves_inventory_releases_owner', 'restart_same_ledger_and_identity'])
    except Exception as exc:
        report['error_type'] = type(exc).__name__
        raise
    finally:
        try:
            if host is not None:
                host.close()
        except Exception as exc:
            report.update(status='failed', cleanup_error_type=type(exc).__name__)
            raise
        finally:
            (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
