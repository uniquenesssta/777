"""P08-02-3 D actual native desktop and TLS Host check; no installer build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(ROOT/'tests')]
from p08_local.scenarios import run


def fingerprints():
    roots=('crates/quote-core','crates/quote-ledger','crates/quote-host','desktop/src-tauri','desktop/src/state','tools/p08_local')
    names={'Cargo.toml','Cargo.lock','.github/workflows/p07-windows.yml','tools/p08_local_check.py'}
    names.update(p.relative_to(ROOT).as_posix() for root in roots for p in (ROOT/root).rglob('*')
                 if p.is_file() and p.suffix in {'.rs','.sql','.json','.toml','.py','.ts'})
    return {name:hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for name in sorted(names)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--manager',required=True,type=Path)
    parser.add_argument('--sales',type=Path)
    parser.add_argument('--auxiliary',action='store_true')
    args=parser.parse_args()
    if os.name!='nt' and not args.auxiliary:parser.error('Actual Windows required for acceptance')
    output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    report=dict(task='P08-02-3-D',status='running',environment=platform.system(),source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),worktree_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),implementation_sha256_LF=fingerprints())
    try:
        report['runtime']=run(args.manager.resolve(),args.sales.resolve() if args.sales else None)
        report['status']='Windows_native_offline_flow_passed_startup_site_pending' if os.name=='nt' else 'auxiliary_native_offline_flow_passed_Windows_pending'
    except Exception as e:
        report['status']='failed';report['failure']=type(e).__name__+': '+str(e)
        (output/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
    report['native_sha256']={kind:hashlib.sha256(path.read_bytes()).hexdigest() for kind,path in [('manager',args.manager),('sales',args.sales)] if path}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary={key:report[key] for key in ('task','status','environment','runtime','failure','native_sha256') if key in report}
    summary['report']=str(output/'report.json')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return int(report['status']=='failed')


if __name__=='__main__':raise SystemExit(main())
