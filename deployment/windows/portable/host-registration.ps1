# Ordinary primary update: no per-package authorization, password or developer handshake.
function Update-HostRegistration([string] $Directory, $Bundle, $Settings) {
    if ($Settings.address -ne '192.168.4.23' -or $Settings.port -ne 8477) { return }
    if ($Bundle.files.PSObject.Properties.Name -notcontains 'host-trust.json') { return }
    $root = $Settings.root
    $native = Join-Path $Directory 'bin\quote-host.exe'
    $candidate = $Bundle.files.'bin/quote-host.exe'
    $deployment = Get-HostDeployment $root $candidate
    # Fail before downtime or native mutation if an existing rule is not ours.
    Initialize-HostRegistrationFirewall $deployment $root
    # Stop through the owned task interface; the native updater also locks the ledger.
    Stop-HostForClusterUpgrade $Directory $root
    $null = Invoke-HostNative $native @('automatic-host-update','--root',$root,'--provision',(Join-Path $Directory 'host-trust.json'),'--notices',(Join-Path $Directory 'THIRD_PARTY_NOTICES.md'))
    Write-HostEvent 'host.registration.configured' @{ledger_id=$deployment.ledger_id}
}
