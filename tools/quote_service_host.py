"""Explicit Windows host initialization / foreground HTTPS service runner."""
import argparse
import getpass
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from quote_service.hosting import initialize,serve,load


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init');init.add_argument('--root',type=Path,required=True);init.add_argument('--backup-dir',type=Path,required=True)
    init.add_argument('--host',action='append',required=True,help='Actual client-facing IP/DNS for certificate SAN; repeat as needed')
    init.add_argument('--bind',default='127.0.0.1');init.add_argument('--port',type=int,default=8477);init.add_argument('--admin',default='manager')
    run=sub.add_parser('run');run.add_argument('--root',type=Path,required=True)
    outputs=sub.add_parser('enable-outputs');outputs.add_argument('--root',type=Path,required=True);outputs.add_argument('--admin',required=True)
    recover=sub.add_parser('restore');recover.add_argument('--package',type=Path,required=True);recover.add_argument('--root',type=Path,required=True);recover.add_argument('--admin',required=True)
    activate=sub.add_parser('activate-restored');activate.add_argument('--root',type=Path,required=True);activate.add_argument('--old-host-stopped',action='store_true',required=True)
    args=parser.parse_args(argv)
    if args.command=='init':
        secret=getpass.getpass('首次管理员密码（12～128字；不显示、不写入命令行）：')
        if secret!=getpass.getpass('再次输入密码：'):parser.error('两次密码不一致')
        config=initialize(args.root,args.backup_dir,args.admin,secret,hosts=args.host,bind=args.bind,port=args.port)
        print('主机初始化完成；当前未启动服务。')
        print('公开证书：',args.root/'service-cert.pem')
        print('证书指纹：',config['certificate_sha256'])
    elif args.command=='enable-outputs':
        import os
        if os.name!='nt':parser.error('Only actual Windows host activation is supported')
        from quote_service.hosting import enable_outputs
        enable_outputs(args.root,args.admin,getpass.getpass('主机管理员密码：'))
        print('输出任务已启用；原账本schema不变，完整维护备份已验证。未启动服务。')
    elif args.command=='restore':
        from quote_service.recovery import restore
        secret=getpass.getpass('恢复管理员的新密码：')
        if secret!=getpass.getpass('再次输入新密码：'):parser.error('两次密码不一致')
        restore(args.package,args.root,args.admin,secret)
        print('已恢复到独立维护目录；旧会话/凭证失效，销售账号需重设密码并启用。尚未启动服务。')
    elif args.command=='activate-restored':
        root,config,service=load(args.root,allow_maintenance=True)
        if not config['maintenance']:parser.error('该主机不是待切换恢复目录')
        from quote_ledger.backup import publish_json
        config['maintenance']=False;publish_json(root/'private/service.json',config)
        print('已登记旧主机停写确认；恢复主机可显式运行。未启动服务。')
    else:serve(args.root)
    return 0


if __name__=='__main__':raise SystemExit(main())
