"""Windows runtime checks for repeatable setup and certificate-pinned diagnostics."""
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import unittest
from test_p08_bundle import fixture
from deployment.bundle.archive import assemble

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell 5.1 runtime requires Windows')
class HostConsoleTests(unittest.TestCase):
    def run_shell(self, script, base, *arguments):
        path = base / 'check.ps1'
        path.write_text(script, encoding='utf-8-sig')
        shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(path), *map(str, arguments)], capture_output=True, text=True, encoding='utf-8', timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_setup_recovers_partial_preparation_and_reuses_running_ledger(self):
        script = r'''
param([string] $Modules,[string] $Base)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
foreach ($name in @('host-log.ps1','host-paths.ps1','host-site.ps1','host-access.ps1','host-registration-firewall.ps1', 'host-registration.ps1','host-setup.ps1')) { . (Join-Path $Modules $name) }
function Set-HostDeploymentVisibility($Directory,$Settings) {}
Start-HostLog $Base
Start-HostLog $Base $env:QUOTE777_LOG_SESSION
function Get-LocalHostInventory { return @{addresses=@('10.20.30.40','192.168.4.38')} }
function Test-HostElevated { return $true }
function Get-HostDeployment($Root) { return @{ledger_id='synthetic-stable-ledger';active_address='10.20.30.40';port=8477} }
function Get-HostConnectionCheck($Directory,$Settings) { return @{tcp=$true;https='verified_response';http_status=401} }
$script:passwords=0; $script:initializations=0; $script:resumes=0
$script:installs=0; $script:starts=0; $script:state='not_registered'; $script:failFirst=$true
function Read-HostBusinessPassword($Confirm) { $script:passwords++; return 'Synthetic-secret-only-in-memory' }
function Invoke-HostPreparation($Site,$Bundle,$Directory,$Root,$Backup,$Hidden,$Admin,$Password,$Address,$Port,$Hour,$Resume) {
    if ($Resume) { $script:resumes++ } else {
        $script:initializations++
        [IO.Directory]::CreateDirectory((Join-Path $Root 'private')) | Out-Null
        [IO.File]::WriteAllText((Join-Path $Root 'private\service.json'),'{}')
        [IO.File]::WriteAllText((Join-Path $Root 'private\rust-service-host.exe'),'synthetic')
    }
    if ($script:failFirst) { $script:failFirst=$false; throw 'SYNTHETIC_INTERRUPTED_PREPARATION' }
    [IO.File]::WriteAllText((Join-Path $Root 'private\deployment.json'),'{}')
}
function Invoke-HostTaskOperation($Directory,$Root,$Operation) {
    switch ($Operation) {
        'status' { return @{state=$script:state} }
        'install' { $script:installs++; $script:state='Ready' }
        'start' { $script:starts++; $script:state='Running' }
        default { throw 'UNEXPECTED_TASK_MUTATION' }
    }
}
$settings=@{root=(Join-Path $Base 'new-host');backup=(Join-Path $Base 'backup');hidden=(Join-Path $Base 'hidden');admin='manager';address='10.20.30.40';port=8477;hour=23}
try { $null=Invoke-HostSetup $Base @{} $settings; throw 'EXPECTED_INTERRUPTION' }
catch { if ($_.Exception.Message -ne 'SYNTHETIC_INTERRUPTED_PREPARATION') { throw } }
if ($script:installs -or $script:starts) { throw 'FAILED_PREPARATION_STARTED_HOST' }
$null=Invoke-HostSetup $Base @{} $settings
$null=Invoke-HostSetup $Base @{} $settings
$null=Invoke-HostSetup $Base @{} $settings
if ($script:initializations -ne 1 -or $script:resumes -ne 1 -or $script:passwords -ne 2 -or $script:installs -ne 1 -or $script:starts -ne 1) { throw 'SETUP_NOT_REPEATABLE' }
$null=Assert-HostSetupMachine @{address='192.168.4.38'}
$settings.address='192.0.2.199'
try { $null=Invoke-HostSetup $Base @{} $settings; throw 'REMOTE_ADDRESS_WAS_ALLOWED' }
catch { if ($_.Exception.Message -ne 'DEPLOYMENT_MUST_RUN_ON_SELECTED_HOST') { throw } }
@{status='passed';initializations=$script:initializations;resumes=$script:resumes;installs=$script:installs;starts=$script:starts} | ConvertTo-Json -Compress
'''
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            value = self.run_shell(script, base, ROOT / 'deployment/windows/portable', base)
            self.assertEqual(value, {'status': 'passed', 'initializations': 1, 'resumes': 1, 'installs': 1, 'starts': 1})
            logs = list((base / 'logs').glob('*/runtime.jsonl'))
            self.assertEqual(len(logs), 1)
            self.assertNotIn('Synthetic-secret-only-in-memory', logs[0].read_text(encoding='utf-8'))

    def test_elevation_cannot_change_the_account_before_setup(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); source, host, worker = fixture(base)
            assemble(source, base / 'bundle', host, worker, 'a' * 40)
            bundle = base / 'bundle/Quote777Host'
            shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(bundle / 'host-console.ps1'), '-Action', 'setup', '-ExpectedSid', 'S-1-5-21-0-0-0-99999', '-NoPause'], capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 1)
            self.assertIn('ELEVATION_MUST_KEEP_ORIGINAL_WINDOWS_ACCOUNT', result.stdout)
            self.assertFalse((bundle / 'logs').exists())

    def test_https_requires_correct_pin_and_expected_service_response(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        class Handler(BaseHTTPRequestHandler):
            status = 401
            body = b'{"error":"UNAUTHENTICATED"}'

            def do_GET(self):
                self.send_response(type(self).status)
                self.send_header('Content-Length', str(len(type(self).body)))
                self.end_headers()
                self.wfile.write(type(self).body)

            def log_message(self, *args):
                pass

        script = r'''
param([string] $Code,[string] $Origin,[string] $Pin)
$ErrorActionPreference='Stop'
Add-Type -Path $Code
[Quote777.HostProbe]::Check($Origin,$Pin) | ConvertTo-Json -Compress
'''
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
            now = datetime.now(timezone.utc)
            certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False).sign(key, hashes.SHA256()))
            cert_path, key_path = base / 'cert.pem', base / 'key.pem'
            cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            pin = hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert_path, key_path)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                arguments = [ROOT / 'deployment/windows/portable/HostProbe.cs', f'https://127.0.0.1:{server.server_port}']
                good = self.run_shell(script, base, *arguments, pin)
                self.assertTrue(good['Tcp'])
                self.assertEqual(good['Https'], 'verified_response')
                self.assertEqual(good['HttpStatus'], 401)
                bad = self.run_shell(script, base, *arguments, '0' * 64)
                self.assertEqual(bad['Https'], 'failed')
                Handler.status = 200; Handler.body = b'{"not":"the quotation service"}'
                unrelated = self.run_shell(script, base, *arguments, pin)
                self.assertEqual(unrelated['Https'], 'unexpected_response')
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
