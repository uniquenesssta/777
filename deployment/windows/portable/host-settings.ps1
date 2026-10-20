# Public per-machine choices; no passwords, certificates' private keys or tickets.
. (Join-Path $PSScriptRoot 'host-layout.ps1')
function Read-HostSettingsJson([string] $Path) {
    if ((Get-Item -LiteralPath $Path).Length -gt 65536) { throw 'HOST_SETUP_SETTINGS_TOO_LARGE' }
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
}
function Get-PreparedHostSettings([string] $Root, $Defaults) {
    $manifest=Join-Path $Root 'private\deployment.json'
    if (Test-Path -LiteralPath $manifest) { $null=Get-HostDeployment $Root }
    $config=Read-HostSettingsJson (Join-Path $Root 'private\service.json')
    $daily=Join-Path $Root 'private\daily-backup.json'
    $hidden=$Defaults.hidden; $hour=$Defaults.hour
    if (Test-Path -LiteralPath $daily) { $plan=Read-HostSettingsJson $daily; if ($plan.hidden_dir) { $hidden=$plan.hidden_dir }; $hour=$plan.daily_hour }
    if ($null -ne $config.daily_backup_hour) { $hour=$config.daily_backup_hour }
    return [pscustomobject]@{root=$Root;backup=$config.backup_dir;hidden=$hidden;admin=$Defaults.admin;address=$config.bind;port=$config.port;hour=$hour;configured=$true}
}
function Get-HostSetupSettings([string] $Directory) {
    $template=Read-HostSettingsJson (Join-Path $Directory 'host-defaults.json')
    if ($template.schema -ne '777-host-setup-v3' -or $template.port -lt 1 -or $template.port -gt 65535 -or $template.hour -lt 0 -or $template.hour -gt 23 -or [string]::IsNullOrWhiteSpace($template.hidden_backup)) { throw 'HOST_SETUP_SETTINGS_INVALID' }
    $site=Get-LocalHostInventory
    $candidates=@(Get-HostCandidateAddresses $site.addresses)
    $address=if ($candidates.Count) { $candidates[0] } else { '' }
    $layout=Get-HostPackageLayout $Directory $template
    $value=[pscustomobject]@{root=$layout.root;backup=$layout.backup;hidden=$layout.hidden;admin=$template.admin;address=$address;port=$template.port;hour=$template.hour;configured=$false}
    $local=Join-Path $Directory 'host-local.json'
    if (Test-Path -LiteralPath $local) {
        $saved=Read-HostSettingsJson $local
        if ($saved.schema -eq '777-host-local-v1' -and $saved.machine -eq $site.machine -and $saved.owner_sid -eq $site.sid) {
            # Never relocate or reset an already prepared local ledger.
            if ([IO.File]::Exists((Join-Path $saved.settings.root 'private\service.json'))) { return Get-PreparedHostSettings $saved.settings.root $value }
            # Retain a selected local interface, but stale unprepared paths cannot override layout.
            if ($saved.settings.root -eq $value.root -and $candidates -contains $saved.settings.address) {
                $value.address=$saved.settings.address
                $value.configured=$true
            }
        } else { Write-HostEvent 'host.settings.foreign_copy_ignored' @{} }
    }
    if ([IO.File]::Exists((Join-Path $value.root 'private\service.json'))) { return Get-PreparedHostSettings $value.root $value }
    return $value
}
function Save-HostSetupSettings([string] $Directory, $Settings) {
    $site=Get-LocalHostInventory
    $Settings.configured=$true
    $saved=[ordered]@{schema='777-host-local-v1';machine=$site.machine;owner_sid=$site.sid;settings=$Settings}
    $path=Join-Path $Directory 'host-local.json'
    $temporary=$path+'.'+[Guid]::NewGuid().ToString('N')+'.partial'
    try {
        [IO.File]::WriteAllText($temporary,($saved | ConvertTo-Json -Depth 10),[Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $path -Force
    } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary } }
}
