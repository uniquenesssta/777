"""Download one hash-pinned OFL font to a new CI-only directory; never install."""
import argparse,hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
URL='https://raw.githubusercontent.com/notofonts/noto-cjk/f8d157532fbfaeda587e826d4cd5b21a49186f7c/Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf'
SHA='d68bafcb48a2707749396aa12bbbd833cb70401f3a9a689fd2902c7e0d295964'
def prepare(root):
    if root.exists():raise FileExistsError('CI font fixture requires a new directory')
    with urllib.request.urlopen(URL,timeout=30) as r:raw=r.read(20*1024*1024+1)
    if len(raw)>20*1024*1024 or hashlib.sha256(raw).hexdigest()!=SHA:raise RuntimeError('CI_FONT_HASH_MISMATCH')
    root.mkdir();(root/'NotoSansSC-VF.ttf').write_bytes(raw)
    data={'schema':'777-CI-font-v1','source':URL,'sha256':SHA,'bytes':len(raw),'license':'SIL Open Font License 1.1','scope':'CI-only explicit font fixture; not a system font installation or a product font selection'}
    (root/'provenance.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8');return data
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);args=p.parse_args();print(json.dumps(prepare(args.root),indent=2))
