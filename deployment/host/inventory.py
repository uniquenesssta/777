"""Read only the current Windows machine's identity and local IP addresses."""
import json
import os
import platform
import subprocess
from .policy import HOST_ORDER


def powershell(script):
    if os.name != 'nt':
        raise ValueError('WINDOWS_DEPLOYMENT_REQUIRED')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('WINDOWS_SITE_INVENTORY_FAILED')
    return json.loads(result.stdout.decode('utf-8-sig'))


def collect():
    value = powershell("""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$ips=@(Get-NetIPAddress -AddressFamily IPv4 | Select-Object -ExpandProperty IPAddress)
[ordered]@{account=$identity.Name;sid=$identity.User.Value;addresses=$ips} | ConvertTo-Json -Compress
""")
    return {'schema': '777-site-inventory-v1', 'os': platform.platform(),
            'machine': platform.node(), **value, 'service_host_order': list(HOST_ORDER),
            'matching_hosts': [h for h in HOST_ORDER if h in value['addresses']],
            'live_host_modified': False, 'replication_available': False}
