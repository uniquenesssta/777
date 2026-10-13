"""Build the accepted P06-02 source into a private fixture, without a branch."""
import atexit
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
ROOT=Path(__file__).resolve().parents[1]
COMMIT='223e86e0bef90dfef083281a42f8d7919b13c07d'
_temp=None
binary=None
build_record=None

def worker():
    global _temp,binary,build_record
    if binary is not None:return binary
    _temp=tempfile.TemporaryDirectory(prefix='777-p06-legacy-worker-');atexit.register(_temp.cleanup);folder=Path(_temp.name)
    paths=['Cargo.toml','Cargo.lock','rust-toolchain.toml','crates/quote-core','crates/quote-ledger','docs/verification/P05-01-schema.sql']
    raw=subprocess.check_output(['git','archive',COMMIT,*paths],cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(raw)) as source:source.extractall(folder,filter='data')
    cargo=shutil.which('cargo');command=[cargo,'+1.97.1','build','--locked','--offline','--release','--bin','quote-ledger','--manifest-path',str(folder/'Cargo.toml')]
    env=dict(os.environ);env['CARGO_TARGET_DIR']=str(folder/'target')
    p=subprocess.run(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=240,check=False)
    build_record=dict(source_commit=COMMIT,command=command,exit_code=p.returncode,stdout=p.stdout.decode('utf-8',errors='replace'),stderr=p.stderr.decode('utf-8',errors='replace'))
    if p.returncode:raise RuntimeError('legacy fixture build failed: '+build_record['stderr'][-3000:])
    binary=folder/'target/release'/('quote-ledger.exe' if os.name=='nt' else 'quote-ledger')
    return binary
