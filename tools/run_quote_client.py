"""Explicit service-mode manager/sales launch; never auto-switch legacy data."""
import argparse
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from quote_app.service_client import application_type
from quote_files.transactions import file_lock


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--role',choices=['manager','sales'],required=True);parser.add_argument('--settings',type=Path)
    args=parser.parse_args(argv)
    if os.name!='nt':parser.error('服务桌面入口仅用于Windows')
    base=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'QuoteProfitCalculator'
    settings=(args.settings or base/(args.role+'-service.json')).absolute();settings.parent.mkdir(parents=True,exist_ok=True)
    with file_lock(settings.with_suffix('.owner')):
        import tkinter as tk
        root=tk.Tk();application_type(args.role,settings)(root);root.mainloop()
    return 0


if __name__=='__main__':raise SystemExit(main())
