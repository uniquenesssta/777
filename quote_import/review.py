"""New review directories; full source/customer/price evidence stays private."""
import json
import os
from pathlib import Path

from quote_ledger.security import protect_directory
from quote_ledger.store import encoded


def write_review(folder, plan, raw):
    folder = Path(folder)
    private = folder / 'private'
    private.mkdir(mode=0o700)
    if os.name == 'nt':
        security = protect_directory(private)
    else:
        security = {'status': 'auxiliary_no_Windows_security_claim'}
    suffix = '.xlsx' if plan.kind == 'xlsx' else '.json'
    with (private / ('source' + suffix)).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    with (private / 'plan.json').open('x', encoding='utf-8') as stream:
        stream.write(encoded(plan.payload()))
        stream.flush()
        os.fsync(stream.fileno())
    report = {**plan.report(), 'mode': 'dry_run', 'private_evidence_must_not_be_shared': True,
              'private_directory_security': security, 'ledger_accessed': False}
    (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report
