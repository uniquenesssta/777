"""Isolated resource comparison runner for the retained Python/Rust-worker host."""
import argparse,json,os,sys,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from quote_service.hosting import load,server
from quote_files.transactions import file_lock

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);a=p.parse_args()
    marker=a.root/'private/p06-isolated-check.json'
    if json.loads(marker.read_text(encoding='utf-8'))!={'schema':'777-isolated-check-v1','production':False}:raise RuntimeError('ISOLATED_CHECK_REQUIRED')
    root,config,service=load(a.root,auxiliary=os.name!='nt')
    if config.get('service_backend')!='python' or config.get('ledger_backend')!='rust':raise RuntimeError('REFERENCE_SELECTION_REQUIRED')
    with file_lock(root/'service-owner'):
        runner=server(service,root/'private/tls-cert.pem',root/'private/tls-key.pem',host=config['bind'],port=config['port'])
        def stop():
            sys.stdin.readline();runner.should_exit=True
        threading.Thread(target=stop,daemon=True).start()
        print(json.dumps({'status':'ready','port':config['port'],'host_backend':'python-rust-worker'}),flush=True)
        runner.run()
    return 0
if __name__=='__main__':raise SystemExit(main())
