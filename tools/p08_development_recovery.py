"""Recover the launcher ledger after an independently addressed TLS Host goes offline."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from native_host_fixture import Hosted


def check_local_recovery(ipc, controller, order_id):
    local = controller.status()
    remote = Hosted()
    try:
        connection = dict(url=f'https://127.0.0.1:{remote.port}',
                          certificate_pem=(remote.host_root / 'service-cert.pem').read_text(),
                          certificate_sha256=remote.config['certificate_sha256'])
        assert connection['certificate_sha256'] != local['connection']['certificate_sha256']
        session = ipc('connect', connection=connection, username='manager', password=remote.password)
        assert session['ledger_id'] == remote.config['ledger_id'] != local['ledger_id']
        assert ipc('bootstrap')['session']['ledger_id'] == remote.config['ledger_id']
        remote.stop()
        try:
            ipc('bootstrap')
        except RuntimeError as error:
            assert 'SERVICE_UNREACHABLE_OR_CERTIFICATE_REJECTED' in str(error), str(error)
        else:
            raise AssertionError('STOPPED_HOST_BOOTSTRAP_SUCCEEDED')
        # Exactly the same status/select sequence used by the new local UI action.
        state = ipc('developer', request=dict(op='status'))
        assert state['root'] == local['root']
        ipc('developer', request=dict(op='select', root=state['root'], backup_dir=state['backup_dir'],
                                      initialize=False, username=None, password=None))
        recovered = ipc('bootstrap')
        assert recovered['session']['ledger_id'] == local['ledger_id']
        assert ipc('connection')['connection'] == local['connection']
        assert ipc('order', order_id=order_id)['order_id'] == order_id
        assert controller.status()['root'] == local['root']
    finally:
        remote.close()
