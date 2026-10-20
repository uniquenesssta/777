# Ordinary primary update: no per-package authorization, password or developer handshake.
function Update-HostRegistration([string] $Directory, $Bundle, $Settings) {
    if ($Settings.address -ne '192.168.4.23' -or $Settings.port -ne 8477) { return }
    if ($Bundle.files.PSObject.Properties.Name -notcontains 'host-trust.json') { return }
    $root = $Settings.root
    $native = Join-Path $Directory 'bin\quote-host.exe'
    $candidate = $Bundle.files.'bin/quote-host.exe'
    $deployment = Get-HostDeployment $root $candidate
    # Stop through the owned task interface; the native updater also locks the ledger.
    Stop-HostForClusterUpgrade $Directory $root
    $null = Invoke-HostNative $native @('automatic-host-update','--root',$root,'--provision',(Join-Path $Directory 'host-trust.json'),'--notices',(Join-Path $Directory 'THIRD_PARTY_NOTICES.md'))
    $name = 'Quote777-Registration-' + $deployment.ledger_id
    $program = Join-Path $root 'private\rust-service-host.exe'
    $description = '777-registration-v1:' + $deployment.ledger_id + ':' + $deployment.owner_sid
    $rule = Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue
    if ($null -ne $rule) {
        $ports = $rule | Get-NetFirewallPortFilter
        $app = $rule | Get-NetFirewallApplicationFilter
        $addresses = $rule | Get-NetFirewallAddressFilter
        if ($rule.Description -ne $description -or $ports.LocalPort -ne '8479' -or $ports.Protocol -ne 'TCP' -or $app.Program -ne $program -or @($addresses.RemoteAddress).Count -ne 1 -or $addresses.RemoteAddress[0] -ne 'LocalSubnet' -or $rule.Action -ne 'Allow' -or $rule.Direction -ne 'Inbound') { throw 'REGISTRATION_FIREWALL_OWNERSHIP_CONFLICT' }
    } else {
        New-NetFirewallRule -Name $name -Description $description -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8479 -Program $program -RemoteAddress LocalSubnet -Profile Domain,Private | Out-Null
    }
    Write-HostEvent 'host.registration.configured' @{ledger_id=$deployment.ledger_id}
}
