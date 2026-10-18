"""Operator-only one-device grants; passwords are prompted and tickets go only into the output file."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quote_service.client import Client
from p08_connection_file import operator_connection


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--connection', type=Path, required=True, help='Host connection.json')
    parser.add_argument('--admin', required=True)
    parser.add_argument('--subject', help='Existing account username; preserves its stable actor ID')
    parser.add_argument('--delivery', choices=['manager', 'sales'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--list-devices', action='store_true')
    parser.add_argument('--revoke', help='Exact device ID; revokes only that device')
    args = parser.parse_args()
    if args.list_devices and args.revoke:
        parser.error('choose one operation')
    if not (args.list_devices or args.revoke) and not all([args.subject, args.delivery, args.output]):
        parser.error('issuing a grant requires --subject, --delivery and --output')
    with operator_connection(args.connection, args.admin) as config:
        client = Client(config)
        client.login(args.admin, getpass.getpass('部署管理员密码：'))
        try:
            if args.list_devices:
                print(json.dumps(client.request('GET', '/v1/devices'), ensure_ascii=False, indent=2))
                return
            if args.revoke:
                import uuid
                if str(uuid.UUID(args.revoke)) != args.revoke:
                    raise ValueError('INVALID_DEVICE_ID')
                client.request('POST', '/v1/devices/' + args.revoke, {})
                print('指定设备已撤销；其他设备保持原授权。')
                return
            accounts = client.request('GET', '/v1/accounts')['accounts']
            user = next(x for x in accounts if x['username'] == args.subject)
            grant = client.request('POST', '/v1/device-grants', {'subject':user['id'], 'delivery':args.delivery, 'ttl_seconds':3600})
            value = dict(schema='777-desktop-bootstrap-v1', delivery=args.delivery,
                         connection=dict(url=config['url'], certificate_pem=Path(config['certificate']).read_text(encoding='utf-8'), certificate_sha256=config['certificate_sha256']), ticket=grant['ticket'])
            for parent in [args.output.parent, *args.output.parent.parents]:
                if parent.exists() and (parent.is_symlink() or getattr(parent.stat(), 'st_file_attributes', 0) & 0x400):
                    raise RuntimeError('DEPLOYMENT_PATH_REPARSE_POINT')
            with args.output.open('xb') as stream:
                stream.write(json.dumps(value, ensure_ascii=True).encode())
                stream.flush()
                os.fsync(stream.fileno())
            print('登记文件已生成，请在一小时内在对应母版/子版的“选择文件”中导入。每台电脑单独签发，勿公开或重复分发。')
        finally:
            client.request('POST', '/v1/logout', {})


if __name__ == '__main__':
    main()
