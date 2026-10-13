"""One source batch, one SQLite transaction; no changes to ledger-v1 DDL.

Source stable IDs are namespaced; unnumbered records keep physical boundaries.
Previously imported lookalikes from a different legacy hash are refused rather
than merged or silently imported twice. No imported catalog becomes active.
"""
from dataclasses import asdict
import base64
import json
import uuid

from quote_core import calculate_quote
from quote_core.numbers import NUMERIC_PROFILE, RULE_VERSION
from quote_ledger.paths import Conflict, LedgerError, UnknownCommit
from quote_ledger.store import encoded, digest, identifier, inventory, now, require_admin, verify
from .adapters import ADAPTER_VERSION, historical_prices, model, preview_bytes

NAMESPACE = uuid.UUID('71146cf4-5cbb-5d58-9841-3e0a57770003')


def uid(value):
    return str(uuid.uuid5(NAMESPACE, value))


def batch_request_id(source_sha256):
    return uid('batch:' + ADAPTER_VERSION + ':' + source_sha256)


def content(order):
    """Ignore sheet positions/OOXML timestamps, retain actual order semantics."""
    result = {k: order[k] for k in ('source_order_id', 'source_price_version', 'source_revision',
                                  'source_time', 'created_at', 'details', 'state',
                                  'snapshot', 'prices', 'totals', 'notes', 'source_events')}
    result['notes'] = [{k: v for k, v in note.items() if k not in ('source_row', 'source_sheet')} for note in order['notes']]
    return result


def order_id(plan, order):
    if order['source_order_id']:
        return uid('identified-order:' + order['source_order_id'])
    return uid('legacy-order:' + plan.source_sha256 + ':' + encoded(order['source_key']))


def verify_provenance(connection):
    """Verify source bytes and review binding against the immutable receipt."""
    count = 0
    for batch in connection.execute('SELECT * FROM import_batches'):
        try:
            if batch['status'] != 'committed' or batch['adapter_version'] != ADAPTER_VERSION:
                raise ValueError('Unknown import record')
            mapping = json.loads(batch['mapping_json'])
            report = json.loads(batch['report_json'])
            raw = base64.b64decode(mapping['source_base64'], validate=True)
            if len(raw) != mapping['source_bytes'] or digest_bytes(raw) != batch['source_sha256']:
                raise ValueError('Source hash mismatch')
            plan = preview_bytes(raw, mapping['source_kind'], legacy_single_names=mapping['options']['legacy_single_names'])
            if plan.source_schema != batch['source_schema'] or plan.review_sha256 != mapping['binding']['review_sha256']:
                raise ValueError('Review mismatch')
            if report['review_sha256'] != plan.review_sha256 or report['owner_id'] != mapping['binding']['owner_id']:
                raise ValueError('Immutable binding mismatch')
            receipt = connection.execute('SELECT * FROM requests WHERE request_id=?', (batch['batch_id'],)).fetchone()
            if (batch['batch_id'] != batch_request_id(batch['source_sha256']) or receipt is None
                    or receipt['operation'] != 'import_batch' or receipt['result_json'] != batch['report_json']):
                raise ValueError('Receipt mismatch')
            if len(mapping['orders']) != len(plan.orders):
                raise ValueError('Order provenance mismatch')
            for saved, original in zip(mapping['orders'], plan.orders):
                if (saved['order_id'] != order_id(plan, original) or saved['content_sha256'] != digest(encoded(content(original)))
                        or saved['source_records'] != original['source_records'] or saved['source_key'] != original['source_key']):
                    raise ValueError('Order mapping mismatch')
            count += 1
        except Exception as exc:
            raise LedgerError('导入来源/映射/不可变回执核对失败；原库保留') from exc
    return count


def digest_bytes(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def apply_source(ledger, actor, owner_id, raw, kind, *, expected_review_sha256,
                 allow_quarantine=False, legacy_single_names=None):
    require_admin(actor)
    identifier(owner_id)
    if type(allow_quarantine) is not bool:
        raise LedgerError('隔离认可参数必须是布尔值')
    # Fresh decode and calculation, never a caller-edited plan/financial DTO.
    plan = preview_bytes(raw, kind, legacy_single_names=legacy_single_names)
    if plan.review_sha256 != expected_review_sha256:
        raise Conflict('来源或导入适配结果已改变；请重新只读预演')
    if plan.source_schema == 'unsupported':
        raise LedgerError('未知/损坏来源只读隔离，不能提交')
    if plan.quarantined and not allow_quarantine:
        raise LedgerError('有隔离记录；仅显式认可隔离报告后可导入已通过部分')
    request_id = batch_request_id(plan.source_sha256)
    binding = {'review_sha256': plan.review_sha256, 'owner_id': owner_id,
               'allow_quarantine': bool(allow_quarantine)}
    commit_attempted = False
    with ledger.connection() as c:
        try:
            c.execute('BEGIN IMMEDIATE')
            verify_provenance(c)
            prior = c.execute('SELECT * FROM import_batches WHERE source_sha256=? AND adapter_version=?',
                              (plan.source_sha256, ADAPTER_VERSION)).fetchone()
            if prior:
                prior_map = json.loads(prior['mapping_json'])
                if prior['status'] != 'committed' or prior_map['binding'] != binding:
                    raise Conflict('同一来源/适配版本已用不同归属或选择登记，不能重新解释')
                c.execute('ROLLBACK')
                return json.loads(prior['report_json'])
            revision = verify(c)['revision']
            previous = []
            for batch in c.execute("SELECT mapping_json FROM import_batches WHERE status='committed'"):
                previous.extend(json.loads(batch['mapping_json']).get('orders', []))
            by_id = {o['order_id']: o for o in previous}
            legacy_semantics = {o['content_sha256'] for o in previous if not o['source_order_id']}
            mappings, line_map, created, reused = [], [], 0, 0

            def record(operation, rid, payload, *, target=None, before=None):
                nonlocal revision
                identifier(rid)
                revision += 1
                result = {**payload, 'request_id': rid, 'ledger_revision': revision}
                fingerprint = digest(encoded({'actor': asdict(actor), 'operation': operation, 'payload': payload}))
                c.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?)',
                          (rid, actor.subject, fingerprint, operation, encoded(result), revision, now()))
                c.execute('INSERT INTO audit_events VALUES(?,?,?,?,?,?,?,?)',
                          (uid('audit:' + rid), rid, actor.subject, operation, target,
                           encoded(before) if before is not None else None, encoded(result), now()))
                c.execute('UPDATE ledger_meta SET revision=? WHERE singleton=1', (revision,))
                return result

            def add_prices(prices):
                payload = encoded({'items': [{'name': p.product_id, 'sale': p.sale, 'cost': p.cost,
                                               'k': p.k, 'single': p.single} for p in prices.items]})
                existing = c.execute('SELECT payload_json FROM price_versions WHERE price_id=?', (prices.price_version_id,)).fetchone()
                if existing:
                    if existing[0] != payload:
                        raise Conflict('历史价格版本身份冲突，原库保留')
                    return
                c.execute('INSERT INTO price_versions VALUES(?,?,?,?,?,?,?)',
                          (prices.price_version_id, payload, digest(payload), RULE_VERSION, NUMERIC_PROFILE, actor.subject, now()))
                record('import_prices', uid('price-request:' + prices.price_version_id),
                       {'price_version_id': prices.price_version_id, 'published_as_active': False})

            if plan.catalog:
                add_prices(historical_prices(plan.catalog['items']))
            for order in plan.orders:
                oid = order_id(plan, order)
                fingerprint = digest(encoded(content(order)))
                existing = c.execute('SELECT owner_id FROM orders WHERE order_id=?', (oid,)).fetchone()
                mapping = {'source_order_id': order['source_order_id'], 'source_key': order['source_key'],
                           'order_id': oid, 'owner_id': owner_id, 'content_sha256': fingerprint,
                           'source_revision': order['source_revision'], 'source_records': order['source_records'],
                           'source_events': order['source_events'], 'normalized_fallbacks': order['normalized_fallbacks']}
                if existing:
                    old = by_id.get(oid)
                    if not old or old['content_sha256'] != fingerprint or existing[0] != owner_id:
                        raise Conflict('已导入稳定订单发生内容/归属变化；批次未提交，不覆盖历史')
                    saved = c.execute('SELECT * FROM orders WHERE order_id=?', (oid,)).fetchone()
                    if (saved['input_json'] != encoded(order['snapshot']) or saved['details_json'] != encoded(order['details'])
                            or saved['created_at'] != order['created_at']
                            or tuple(saved[k] for k in ('income_cents', 'cost_cents', 'profit_cents'))
                            != tuple(order['totals'][k] for k in ('income_cents', 'cost_cents', 'profit_cents'))):
                        raise Conflict('稳定订单与源快照实际内容不一致；批次未提交')
                    reused += 1
                    mapping['reused_existing'] = True
                    for row in order['source_records']:
                        old_line = next((x for x in old.get('row_map', []) if x.get('source_line_id') == row['values'].get('明细ID')), None)
                        if old_line:
                            line_map.append({**old_line, 'source_row': row['row']})
                    mapping['row_map'] = [m for m in line_map if m['order_id'] == oid]
                    mapping['note_map'] = []
                    for index, note in enumerate(order['notes']):
                        nrid = uid('note-request:' + oid + ':' + str(note.get('source_request_id', note.get('source_row', index))))
                        nm = {'source_sheet': note['source_sheet'], 'source_row': note['source_row'],
                              'source_request_id': note.get('source_request_id'), 'order_id': oid,
                              'note_id': uid('note:' + nrid), 'request_id': nrid}
                        mapping['note_map'].append(nm)
                        line_map.append(nm)
                    mappings.append(mapping)
                    continue
                if not order['source_order_id'] and fingerprint in legacy_semantics:
                    raise Conflict('新来源哈希含与既有无编号历史相似的订单，需人工核查，未合并或重复入账')
                prices, snapshot = model(order)
                result = calculate_quote(snapshot, prices)
                if result.status != 'ok':
                    raise LedgerError('导入核心重验失败')
                add_prices(prices)
                rid = uid('order-request:' + oid)
                amounts = result.totals
                c.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          (oid, owner_id, prices.price_version_id, RULE_VERSION, NUMERIC_PROFILE,
                           encoded(asdict(snapshot)), encoded(order['details']), amounts.income_cents,
                           amounts.cost_cents, amounts.profit_cents, order['state'], 1, order['created_at'], rid))
                details = [row for row in order['source_records'] if row['values'].get('行类型') != 'order_total'
                           and row['values'].get('项目名称') != '--- 本次总计 ---']
                # A typed normal product named like a footer remains a product.
                if '行类型' in order['source_records'][0]['values']:
                    details = [row for row in order['source_records'] if row['values']['行类型'] in ('normal', 'discount')]
                row_map = []
                for line, source_row in zip(result.lines, details):
                    source_lid = source_row['values'].get('明细ID')
                    lid = uid('line:' + oid + ':' + str(source_lid or line.sequence))
                    c.execute('INSERT INTO lines VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                              (lid, oid, line.sequence, line.raw.line_kind, encoded(asdict(line.raw)),
                               encoded(dict(line.normalized)), encoded(asdict(line.price)) if line.price else None,
                               line.amounts.income_cents, line.amounts.cost_cents, line.amounts.profit_cents,
                               line.subtotal_before_cents))
                    row_map.append({'source_sheet': '利润明细', 'source_row': source_row['row'],
                                    'source_line_id': source_lid, 'order_id': oid, 'line_id': lid})
                    if ledger.fault:
                        ledger.fault('import_line_inserted', c)
                for row in order['source_records']:
                    if row['row'] not in {m['source_row'] for m in row_map}:
                        row_map.append({'source_sheet': '利润明细', 'source_row': row['row'],
                                        'source_line_id': row['values'].get('明细ID'), 'order_id': oid, 'line_id': None})
                record('import_order', rid, {'order_id': oid, 'revision': 1, 'state': order['state'],
                                            'source_revision': order['source_revision'], **amounts.cents_payload()}, target=oid)
                note_map = []
                for index, note in enumerate(order['notes']):
                    note_rid = uid('note-request:' + oid + ':' + str(note.get('source_request_id', note.get('source_row', index))))
                    nid = uid('note:' + note_rid)
                    c.execute('INSERT INTO notes VALUES(?,?,?,?,?,?)',
                              (nid, oid, actor.subject, note['body'], note['created_at'], note_rid))
                    record('import_note', note_rid, {'order_id': oid, 'note_id': nid, 'source_note': note}, target=oid)
                    note_map.append({'source_sheet': note['source_sheet'], 'source_row': note['source_row'],
                                     'source_request_id': note.get('source_request_id'), 'order_id': oid,
                                     'note_id': nid, 'request_id': note_rid})
                mapping['row_map'] = row_map
                mapping['note_map'] = note_map
                mapping['reused_existing'] = False
                line_map.extend(row_map)
                line_map.extend(note_map)
                mappings.append(mapping)
                created += 1
            checked = inventory(c)
            final_inventory = {**checked, 'revision': checked['revision'] + 1,
                               'counts': {**checked['counts'], 'requests': checked['counts']['requests'] + 1,
                                          'audit_events': checked['counts']['audit_events'] + 1,
                                          'import_batches': checked['counts']['import_batches'] + 1}}
            report = {**plan.report(), 'status': 'committed', 'batch_id': request_id,
                      'owner_id': owner_id, 'owner_assignment': 'explicit archival custodian; historical operator unknown',
                      'created_orders': created, 'reused_identified_orders': reused,
                      'row_map': line_map, 'post_import_inventory': final_inventory,
                      'order_revision_policy': 'New archive revision1; original revision and events preserved as provenance.'}
            result = record('import_batch', request_id, report)
            mapping = {'binding': binding, 'orders': mappings, 'file_evidence': plan.file_evidence,
                       'quarantined': list(plan.quarantined), 'source_schema': plan.source_schema,
                       'source_kind': kind, 'options': plan.options,
                       'source_bytes': len(raw), 'source_base64': base64.b64encode(raw).decode('ascii')}
            c.execute('INSERT INTO import_batches VALUES(?,?,?,?,?,?,?,?)',
                      (request_id, plan.source_sha256, ADAPTER_VERSION, plan.source_schema, 'committed',
                       encoded(mapping), encoded(result), now()))
            if inventory(c) != final_inventory:
                raise LedgerError('导入前后完整账本核对失败；批次回滚')
            verify_provenance(c)
            if ledger.fault:
                ledger.fault('import_before_commit', c)
            commit_attempted = True
            c.execute('COMMIT')
            if ledger.fault:
                ledger.fault('import_after_commit', c)
            return result
        except BaseException as exc:
            if c.in_transaction:
                c.execute('ROLLBACK')
            if commit_attempted:
                raise UnknownCommit(request_id) from exc
            raise
