"""Windows local administrative import. Preview defaults to read-only evidence.

Apply requires an explicit host, administrator login, archival owner, reviewed
digest, and a complete maintenance backup. The host owner lock excludes its
running HTTPS process. No production path or migration is selected by default.
"""
import argparse
import getpass
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]

from p01_validation import new_output
from quote_import import preview_bytes, read_source, apply_source, batch_request_id
from quote_import.adapters import ReviewRequired
from quote_import.review import write_review
from quote_files.transactions import file_lock
from quote_ledger.store import require_admin
from quote_ledger.paths import UnknownCommit
from quote_service.hosting import load
from quote_service.auth import username


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('preview', 'apply'):
        child = sub.add_parser(command)
        child.add_argument('--source', type=Path, required=True)
        child.add_argument('--legacy-single', nargs='*', default=None,
                           help='Explicit single-item names for legacy price JSON; empty list means all area products')
        child.add_argument('--output', type=Path, required=True)
        if command == 'apply':
            child.add_argument('--host-root', type=Path, required=True)
            child.add_argument('--username', required=True)
            child.add_argument('--owner', required=True, help='Existing archival custodian account, not the legacy customer')
            child.add_argument('--review-sha256', required=True)
            child.add_argument('--allow-quarantine', action='store_true')
    args = parser.parse_args(argv)
    if platform.system() != 'Windows':
        print(json.dumps({'task': 'P05-03', 'status': 'blocked', 'reason': 'Actual Windows local import entry required'}, ensure_ascii=False))
        return 2
    output = new_output(args.output)
    report = {'task': 'P05-03', 'mode': args.command, 'status': 'failed', 'source_modified': False}
    token = service = None
    try:
        kind = {'xlsx': 'xlsx', 'json': 'json'}.get(args.source.suffix.lower().lstrip('.'))
        if kind is None:
            raise ValueError('只支持显式选择的.xlsx或.json')
        raw = read_source(args.source)
        plan = preview_bytes(raw, kind, legacy_single_names=args.legacy_single)
        if args.command == 'preview':
            report = write_review(output, plan, raw)
        else:
            report = {**plan.report(), 'mode': 'apply', 'status': 'failed'}
            if plan.review_sha256 != args.review_sha256:
                raise ValueError('来源/适配结果已改变，请重新预演')
            # This is the same owner lock held by quote_service_host.run.
            validated_root, _, _ = load(args.host_root, allow_maintenance=True)
            with file_lock(validated_root / 'service-owner'):
                root, config, service = load(args.host_root, allow_maintenance=True)
                login = service.auth.login(args.username, getpass.getpass('管理员密码（不显示、不保存）：'), 'local-import')
                token = login['token']
                actor = service.auth.authenticate(token)
                require_admin(actor)
                with service.auth.connection() as c:
                    owner = c.execute('SELECT id,enabled FROM users WHERE username=?', (username(args.owner),)).fetchone()
                if owner is None or not owner['enabled']:
                    raise ValueError('归属必须为已启用的现有账户；不从淘宝ID推断')
                if plan.source_schema == 'unsupported' or (plan.quarantined and not args.allow_quarantine):
                    raise ValueError('来源未通过或隔离部分未经显式认可')
                # Failure here must leave the live ledger unchanged.
                backup = service.backup(kind='maintenance')
                if not backup.get('service_bundle'):
                    raise ValueError('完整服务维护备份未验证，不能导入')
                committed = apply_source(service.ledger, actor, owner['id'], raw, kind,
                                         expected_review_sha256=plan.review_sha256,
                                         allow_quarantine=args.allow_quarantine,
                                         legacy_single_names=args.legacy_single)
                report = {**committed, 'mode': 'apply', 'complete_pre_import_backup': True,
                          'backup_id': backup.get('backup_id'), 'host_ledger_id': service.ledger.inventory()['ledger_id']}
    except UnknownCommit as exc:
        report.update(status='commit_unknown', request_id=exc.request_id,
                      reason='保留原来源/归属/预演SHA并重试；批次按原ID核查，不新建请求')
    except Exception as exc:
        # Source contents, customer names, host-private paths and passwords stay out.
        report.update(error_type=type(exc).__name__, reason=str(exc) if isinstance(exc, (ValueError, ReviewRequired)) else '导入未完成，请核对来源/身份/锁/备份；原源件保留')
    finally:
        if token and service:
            try:
                service.auth.logout(token)
            except Exception as exc:
                report['session_cleanup_error'] = type(exc).__name__
    saved = False
    try:
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        saved = True
    except OSError as exc:
        report['report_save_error'] = type(exc).__name__
    print(json.dumps({k: v for k, v in report.items() if k not in ('row_map', 'post_import_inventory')}, ensure_ascii=False, indent=2))
    if saved:
        print('报告：', output / 'report.json')
    elif report['status'] == 'committed':
        print('报告保存失败；导入已提交，可用原请求ID核查。')
    elif report['status'] == 'commit_unknown':
        print('报告保存失败；提交结果仍待按原请求ID核查。')
    else:
        print('报告保存失败；本次未完成导入，原源件保留。')
    return 0 if report['status'] in ('ready', 'review_required', 'committed') else 2


if __name__ == '__main__':
    raise SystemExit(main())
