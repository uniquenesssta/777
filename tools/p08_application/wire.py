"""Synthetic offline wire data and canonical digests; never authorization results."""
import hashlib
import json
import uuid

FORMAT = '777-offline-order-v1'
PROTOCOLS = dict(issuance='777-package-issuance-v1', enrollment='777-auto-enrollment-v1',
                 scoped_auth='777-scoped-auth-v1', cluster_snapshot='777-cluster-snapshot-v2')


def identifier():
    return str(uuid.uuid4())

def envelope(protocol, **fields):
    return dict(protocol=protocol, request_id=identifier(), **fields)

def seal(value):
    value = {key: item for key, item in value.items() if key != 'content_sha256'}
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    value['content_sha256'] = hashlib.sha256(FORMAT.encode() + b'\n' + raw).hexdigest()
    return value

def operation(lease, sequence, *, kind='create', order=None, base=None, payload=None):
    from datetime import datetime, timezone
    value = dict(protocol=FORMAT, site_id=lease['site_id'], ledger_id=lease['ledger_id'], device_id=lease['device_id'],
                 stream_id=lease['stream_id'], owner_id=lease['subject'], lease_id=lease['lease_id'],
                 operation_id=identifier(), device_sequence=str(sequence), order_id=order or identifier(), kind=kind,
                 base=base or dict(order_revision=None, previous_operation_id=None),
                 created_at=datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z'),
                 rule_version=lease['rule_version'], numeric_profile=lease['numeric_profile'], payload=payload or dict(
                     snapshot=dict(price_version_id=lease['price_version_id'], lines=[dict(line_id=identifier(), raw=dict(line_kind='normal', product_id='单件', q='1'))]),
                     details=dict(customer='isolated-C', order_ref=f'loopback-{sequence}', wechat=''), customer=dict(new_customer=True)))
    return seal(value)
