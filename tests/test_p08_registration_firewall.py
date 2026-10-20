"""Execute deployment functions with controlled Windows firewall/task boundaries."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell 5.1 requires Windows')
class RegistrationFirewallTests(unittest.TestCase):
    def check_case(self, case):
        shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(
                [str(shell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                 '-File', str(ROOT / 'tests/fixtures/p08_registration_firewall.ps1'),
                 '-Modules', str(ROOT / 'deployment/windows/portable'), '-Case', case, '-Base', folder],
                capture_output=True, text=True, encoding='utf-8', timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), {'status': 'passed', 'case': case})

    def test_scalar_array_and_numeric_protocol_equivalence(self):
        self.check_case('equivalent')

    def test_real_conflicts_log_fields_before_stopping_or_updating(self):
        self.check_case('conflicts')

    def test_duplicate_rule_is_rejected_before_downtime(self):
        self.check_case('duplicate')

    def test_create_readback_and_reuse(self):
        self.check_case('create-reuse')

    def test_firewall_creation_failure_keeps_host_untouched(self):
        self.check_case('creation-failure')

    def test_retry_setup_starts_existing_disabled_host(self):
        self.check_case('resume-setup')
