"""Daily delivery contract over real HTTPS, including the Host's automatic retry."""
import json
import time
from contextlib import contextmanager

from quote_service.protocol import APIError


@contextmanager
def unavailable(directory):
    parked = directory.with_name(directory.name + ' temporarily offline')
    directory.rename(parked)
    try:
        directory.write_text('unavailable', encoding='utf-8')
        yield
    finally:
        directory.unlink()
        parked.rename(directory)


def assert_delivery(client, controller, hidden, *, normal_ok, hidden_ok):
    health = controller.status()['daily_result']
    assert health['normal']['ok'] is normal_ok, health
    assert health['hidden']['ok'] is hidden_ok, health
    public = client.request('GET', '/v1/backup')
    assert public['delivery_complete'] is (normal_ok and hidden_ok), public
    expected = 'complete' if normal_ok and hidden_ok else 'partial'
    assert public['delivery_state'] == expected, public
    encoded = json.dumps(public)
    assert json.dumps(str(hidden)) not in encoded and 'hidden_dir' not in encoded, public


def await_automatic_delivery(client, controller, hidden, entry):
    # Only read status here: a manual POST would conceal a broken scheduler.
    deadline = time.monotonic() + 15
    while True:
        public = client.request('GET', '/v1/backup')
        if public['delivery_complete']:
            break
        assert time.monotonic() < deadline, ('AUTOMATIC_BACKUP_RETRY_TIMEOUT', public)
        time.sleep(.1)
    assert_delivery(client, controller, hidden, normal_ok=True, hidden_ok=True)
    health = controller.status()['daily_result']
    assert health['snapshot_id'] == entry['backup_id'], health
    # After automatic recovery, a manual repeat must still reuse the complete receipt.
    assert client.request('POST', '/v1/backup', {'kind': 'daily'}) == entry


def check_delivery_recovery(client, controller, normal, hidden, entry):
    assert entry['delivery_complete'] is True, entry
    with unavailable(hidden):
        partial = client.request('POST', '/v1/backup', {'kind': 'daily'})
        # Snapshot identity, date, format and verification stay immutable; delivery
        # truth must change instead of claiming that both copies are available.
        assert partial == {**entry, 'delivery_complete': False}, partial
        assert_delivery(client, controller, hidden, normal_ok=True, hidden_ok=False)
    await_automatic_delivery(client, controller, hidden, entry)

    with unavailable(normal):
        try:
            client.request('POST', '/v1/backup', {'kind': 'daily'})
        except APIError as error:
            assert error.status == 503 and error.code == 'DAILY_BACKUP_FAILED', str(error)
        else:
            raise AssertionError('FAILED_NORMAL_BACKUP_REPORTED_SUCCESS')
        assert_delivery(client, controller, hidden, normal_ok=False, hidden_ok=True)
    await_automatic_delivery(client, controller, hidden, entry)
