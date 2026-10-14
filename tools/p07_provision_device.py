"""Operator-only preparation of one limited enrollment file; no secrets on the command line."""
import argparse, getpass, json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from quote_service.client import Client

def main():
    p=argparse.ArgumentParser();p.add_argument('--connection',type=Path,required=True);p.add_argument('--admin',required=True);p.add_argument('--subject',required=True,help='Existing account username; preserves its stable actor ID');p.add_argument('--delivery',choices=['manager','sales'],required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    config=json.loads(a.connection.read_text(encoding='utf-8'));client=Client(config)
    client.login(a.admin,getpass.getpass('部署管理员密码：'))
    try:
        accounts=client.request('GET','/v1/accounts')['accounts'];user=next(x for x in accounts if x['username']==a.subject)
        grant=client.request('POST','/v1/device-grants',{'subject':user['id'],'delivery':a.delivery,'ttl_seconds':3600})
        value={'schema':'777-desktop-bootstrap-v1','delivery':a.delivery,'connection':{'url':config['url'],'certificate_pem':Path(config['certificate']).read_text(encoding='utf-8'),'certificate_sha256':config['certificate_sha256']},'ticket':grant['ticket']}
        for parent in [a.output.parent,*a.output.parent.parents]:
            if parent.exists() and (parent.is_symlink() or getattr(parent.stat(),'st_file_attributes',0)&0x400):raise RuntimeError('DEPLOYMENT_PATH_REPARSE_POINT')
        with a.output.open('xb') as f:f.write(json.dumps(value,ensure_ascii=True).encode());f.flush();os.fsync(f.fileno())
        print('一次性登记文件已生成；请在一小时内由部署人员放入对应原生profile的 bootstrap.json，勿公开或重复分发。')
    finally:
        client.request('POST','/v1/logout',{})
if __name__=='__main__':main()
