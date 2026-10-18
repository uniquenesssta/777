# Current Windows machine only; no remote probes or configuration changes.
function Get-LocalHostInventory {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return [ordered]@{schema='777-site-inventory-v1';machine=$env:COMPUTERNAME;os=[Environment]::OSVersion.VersionString;account=$identity.Name;sid=$identity.User.Value;addresses=@(Get-NetIPAddress -AddressFamily IPv4 | Select-Object -ExpandProperty IPAddress);live_host_modified=$false;replication_available=$false}
}
