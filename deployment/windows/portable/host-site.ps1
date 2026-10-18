# Current Windows machine only; no remote probes or configuration changes.
function Get-LocalHostInventory {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return [ordered]@{schema='777-site-inventory-v1';machine=$env:COMPUTERNAME;os=[Environment]::OSVersion.VersionString;account=$identity.Name;sid=$identity.User.Value;addresses=@(Get-NetIPAddress -AddressFamily IPv4 | Select-Object -ExpandProperty IPAddress);live_host_modified=$false;replication_available=$false}
}
function Get-HostCandidateAddresses($Addresses) {
    return @($Addresses | Where-Object {
        $ip=$null
        [Net.IPAddress]::TryParse([string]$_,[ref]$ip) -and $ip.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork -and
        -not [Net.IPAddress]::IsLoopback($ip) -and $ip.GetAddressBytes()[0] -gt 0 -and $ip.GetAddressBytes()[0] -lt 224 -and
        -not ([string]$_).StartsWith('169.254.')
    } | Sort-Object -Unique)
}
function Assert-HostLocalAddress([string] $Address, $Addresses) {
    if ($Address -notin @(Get-HostCandidateAddresses $Addresses)) { throw 'DEPLOYMENT_MUST_RUN_ON_SELECTED_HOST' }
}
