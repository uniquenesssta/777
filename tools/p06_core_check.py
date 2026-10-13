"""P06-01 locked Rust build and exact Python/Rust shadow comparison; no production I/O."""
import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'), str(ROOT/'tests')]
from p01_validation import new_output
from p03_format_check import case_ids
import p06_cases
TOOLCHAIN = '1.97.1'


def fingerprints():
    paths = [ROOT/'Cargo.toml', ROOT/'Cargo.lock', ROOT/'rust-toolchain.toml', Path(__file__),
        ROOT/'tools/p06_cases.py', ROOT/'tools/p01_oracle.py', ROOT/'docs/baseline/p01-04-golden.json',
        ROOT/'docs/baseline/p01-04-numeric-profile.json', ROOT/'docs/baseline/p01-acceptance.json',
        ROOT/'docs/verification/P06-01-protocol.json', ROOT/'docs/verification/P06-01-dependencies.json',
        ROOT/'THIRD_PARTY_NOTICES.md']
    paths += list((ROOT/'crates/quote-core').rglob('*.rs')) + [ROOT/'crates/quote-core/Cargo.toml']
    paths += list((ROOT/'quote_core').glob('*.py'))
    paths += [ROOT/'tests'/p for p in ('test_quote_core.py','test_price_configuration.py','test_quote_session.py','test_p06_core_check.py')]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in sorted(paths)}


def run(command, timeout=240):
    start = time.monotonic()
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    p = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
    record = dict(command=command, exit_code=p.returncode, elapsed_seconds=time.monotonic()-start,
        stdout=p.stdout.decode('utf-8', errors='replace'), stderr=p.stderr.decode('utf-8', errors='replace'))
    return record


def first_difference(expected, actual, path='$'):
    if type(expected) is not type(actual): return dict(path=path, expected=expected, actual=actual)
    if isinstance(expected, dict):
        if expected.keys() != actual.keys(): return dict(path=path, expected=list(expected), actual=list(actual))
        for key in expected:
            d = first_difference(expected[key], actual[key], path+'.'+key)
            if d is not None: return d
    elif isinstance(expected, list):
        if len(expected) != len(actual): return dict(path=path+'.length', expected=len(expected), actual=len(actual))
        for i, (a,b) in enumerate(zip(expected, actual)):
            d = first_difference(a,b,f'{path}[{i}]')
            if d is not None: return d
    elif expected != actual: return dict(path=path, expected=expected, actual=actual)
    return None


def run_python_checks():
    suite=unittest.defaultTestLoader.loadTestsFromNames(['test_quote_core','test_price_configuration','test_quote_session','test_p06_core_check'])
    ids=list(case_ids(suite)); log=io.StringIO(); result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    return dict(status='passed' if result.wasSuccessful() else 'failed', tests_run=result.testsRun,
        failures=len(result.failures), errors=len(result.errors), skipped=result.skipped, test_ids=ids, log=log.getvalue())


def compare(binary, output):
    cases=list(p06_cases.cases()); requests=[cmd for _,_,cmd in cases]
    payload=''.join(json.dumps(cmd,ensure_ascii=True,separators=(',',':'))+'\n' for cmd in requests).encode('utf-8')
    p=subprocess.run([str(binary)],input=payload,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=ROOT,timeout=120,check=False)
    lines=p.stdout.splitlines()
    if p.returncode or len(lines)!=len(cases): raise RuntimeError(f'SHADOW_PROCESS_FAILED: exit={p.returncode}, responses={len(lines)}, expected={len(cases)}')
    results=[]
    for (category,case_id,cmd),line in zip(cases,lines):
        expected=p06_cases.reference(cmd);actual=json.loads(line);difference=first_difference(expected,actual)
        results.append(dict(category=category,case_id=case_id,passed=difference is None,difference=difference,
            request_sha256=hashlib.sha256(json.dumps(cmd,ensure_ascii=True,sort_keys=True).encode()).hexdigest(),
            python_result_sha256=hashlib.sha256(json.dumps(expected,ensure_ascii=True,sort_keys=True).encode()).hexdigest(),
            rust_result_sha256=hashlib.sha256(json.dumps(actual,ensure_ascii=True,sort_keys=True).encode()).hexdigest()))
    (output/'comparisons.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return dict(status='passed' if all(r['passed'] for r in results) else 'failed', cases_run=len(cases),
        categories=dict(Counter(r['category'] for r in results)), failed=[r for r in results if not r['passed']],
        full_comparison_artifact='comparisons.json', artifact_sha256=hashlib.sha256((output/'comparisons.json').read_bytes()).hexdigest(),
        stderr=p.stderr.decode('utf-8',errors='replace'))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--windows-smoke',action='store_true');mode.add_argument('--checks-only',action='store_true')
    parser.add_argument('--output',required=True)
    args=parser.parse_args(argv);output=new_output(args.output)
    report=dict(task='P06-01',status='running',environment=dict(os=platform.system(),python=platform.python_version()),
        source_commit=None,implementation_sha256_LF=None,commands=[],python_checks=None,shadow_comparison=None,
        production_paths_accessed=False,production_writer_replaced=False,Windows_acceptance='pending')
    try:
        if args.windows_smoke and platform.system()!='Windows': raise RuntimeError('ACTUAL_WINDOWS_REQUIRED')
        report['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,encoding='utf-8').strip()
        report['worktree_dirty']=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True,encoding='utf-8').strip())
        report['implementation_sha256_LF']=fingerprints()
        cargo=shutil.which('cargo');rustc=shutil.which('rustc')
        if cargo is None or rustc is None: raise RuntimeError('RUST_1_97_1_AND_WINDOWS_MSVC_BUILD_TOOLS_REQUIRED')
        v=run([rustc,'+'+TOOLCHAIN,'-vV']);report['commands'].append(v)
        if v['exit_code'] or not v['stdout'].startswith('rustc 1.97.1 '): raise RuntimeError('PINNED_RUST_TOOLCHAIN_REQUIRED')
        report['environment']['rustc']=v['stdout'].strip()
        host=next((l.removeprefix('host: ') for l in v['stdout'].splitlines() if l.startswith('host: ')),None)
        if args.windows_smoke and host!='x86_64-pc-windows-msvc': raise RuntimeError('WINDOWS_AMD64_MSVC_HOST_REQUIRED')
        for command in [[cargo,'+'+TOOLCHAIN,'fmt','--all','--','--check'],
                        [cargo,'+'+TOOLCHAIN,'clippy','--locked','--workspace','--all-targets','--','-D','warnings'],
                        [cargo,'+'+TOOLCHAIN,'test','--locked','--workspace'],
                        [cargo,'+'+TOOLCHAIN,'build','--locked','--release','--bin','quote-shadow']]:
            record=run(command);report['commands'].append(record)
            if record['exit_code']: raise RuntimeError('RUST_CHECK_FAILED: '+' '.join(command[2:]))
        metadata=run([cargo,'+'+TOOLCHAIN,'metadata','--locked','--format-version','1']);
        if metadata['exit_code']:raise RuntimeError('CARGO_METADATA_FAILED')
        packages=json.loads(metadata['stdout'])['packages'];report['dependencies']=[dict(name=p['name'],version=p['version'],license=p['license']) for p in packages]
        expected=json.loads((ROOT/'docs/verification/P06-01-dependencies.json').read_text(encoding='utf-8'))['packages']
        external={p['name']:(p['version'],p['license']) for p in packages if p['source'] is not None}
        if external!={p['name']:(p['version'],p['license']) for p in expected}:raise RuntimeError('LOCKED_DEPENDENCY_OR_LICENSE_MISMATCH')
        report['python_checks']=run_python_checks()
        binary=ROOT/'target/release'/('quote-shadow.exe' if platform.system()=='Windows' else 'quote-shadow')
        report['shadow_binary_sha256']=hashlib.sha256(binary.read_bytes()).hexdigest()
        report['shadow_comparison']=compare(binary,output)
        if report['python_checks']['status']=='passed' and report['shadow_comparison']['status']=='passed':
            report['status']='Windows_Rust_shadow_passed_acceptance_pending' if args.windows_smoke else 'auxiliary_Rust_shadow_passed_Windows_pending'
            if args.windows_smoke:report['Windows_acceptance']='native_MSVC_Rust_build_and_shadow_passed_user_acceptance_pending'
        else:report['status']='failed'
    except Exception as e:
        report['status']='failed';report['failure']=dict(reason=str(e),traceback=traceback.format_exc())
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary={key:report[key] for key in ['task','status','environment','Windows_acceptance','production_paths_accessed','production_writer_replaced']}
    for key in ['python_checks','shadow_comparison']:
        value=report[key];summary[key]=None if value is None else {k:v for k,v in value.items() if k not in ['log','test_ids']}
    if 'failure' in report:summary['failure']=report['failure']['reason']
    summary['report_path']=str(output/'report.json');print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0 if report['status'] in ['Windows_Rust_shadow_passed_acceptance_pending','auxiliary_Rust_shadow_passed_Windows_pending'] else 1

if __name__=='__main__':raise SystemExit(main())
