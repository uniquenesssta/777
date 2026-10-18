# Native initialization and authenticated retries. Never delete or replace a ledger.
function Write-HostJsonNew([string] $Path, $Value) {
    $json = $Value | ConvertTo-Json -Depth 20 -Compress
    if (Test-Path -LiteralPath $Path) {
        $existing = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
        if (($existing | ConvertTo-Json -Depth 20 -Compress) -cne $json) { throw 'EXISTING_DEPLOYMENT_FILE_CONFLICT' }
        return
    }
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json + "`n")
    $stream = [IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try { $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
}
function Invoke-HostPreparation($Site, $Bundle, [string] $Directory, [string] $Root, [string] $Backup, [string] $Hidden, [string] $Admin, $Password, [string] $Address, [int] $Port, [int] $Hour, [bool] $Resume) {
    if ($Address -notin @('192.168.4.23','192.168.4.38')) { throw 'DEPLOYMENT_HOST_NOT_IN_PLAN' }
    if ($Address -notin $Site.addresses) { throw 'DEPLOYMENT_MUST_RUN_ON_SELECTED_HOST' }
    if ($Address -ne '192.168.4.23') { throw 'STANDBY_REPLICATION_NOT_IMPLEMENTED' }
    $Root = Get-LocalHostRoot $Root (-not $Resume)
    if ($Port -lt 1 -or $Port -gt 65535 -or $Hour -lt 0 -or $Hour -gt 23) { throw 'DEPLOYMENT_PORT_OR_HOUR_INVALID' }
    Assert-HostBackupLocation $Backup $Root
    Assert-HostBackupLocation $Hidden $Root
    if ([string]::IsNullOrWhiteSpace($Admin)) { throw 'DEPLOYMENT_INPUT_REQUIRED' }
    $saved = $null
    if (Test-Path -LiteralPath (Join-Path $Root 'private\deployment.json')) { $saved = Get-HostDeployment $Root }
    $native = Join-Path $Root 'private\rust-service-host.exe'
    if ($Resume) {
        $null = Invoke-HostNative $native @('authorize','--root',$Root,'--admin',$Admin) $Password
        $probe = Invoke-HostNative $native @('inspect','--root',$Root)
        if ($probe.shutdown_control -ne 'stdin-v1') { throw 'HOST_RESOURCE_UPGRADE_REQUIRED_FOR_DEPLOYMENT' }
        $config = Get-Content -LiteralPath (Join-Path $Root 'private\service.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($config.bind -ne $Address -or $config.port -ne $Port) { throw 'EXISTING_HOST_ENDPOINT_CONFLICT' }
    } else {
        $null = Invoke-HostNative (Join-Path $Directory 'bin\quote-host.exe') @('init','--root',$Root,'--backup-dir',$Backup,'--host',$Address,'--host','127.0.0.1','--host','localhost','--bind',$Address,'--port',[string]$Port,'--admin',$Admin,'--worker',(Join-Path $Directory 'bin\quote-ledger.exe'),'--notices',(Join-Path $Directory 'THIRD_PARTY_NOTICES.md')) $Password
    }
    $null = Invoke-HostNative $native @('enable-devices','--root',$Root,'--admin',$Admin) $Password
    $null = Invoke-HostNative $native @('configure-daily','--root',$Root,'--backup-dir',$Backup,'--hidden-dir',$Hidden,'--daily-hour',[string]$Hour,'--admin',$Admin) $Password
    $checked = Invoke-HostNative $native @('inspect','--root',$Root)
    if ($checked.shutdown_control -ne 'stdin-v1') { throw 'HOST_RESOURCE_UPGRADE_REQUIRED_FOR_DEPLOYMENT' }
    $template = Get-Content -LiteralPath (Join-Path $Root 'client-template.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $public = [ordered]@{schema='777-public-connection-v1';connection=[ordered]@{url=$template.url;certificate_pem=[IO.File]::ReadAllText((Join-Path $Root 'service-cert.pem'));certificate_sha256=$template.certificate_sha256}}
    Write-HostJsonNew (Join-Path $Root 'connection.json') $public
    foreach ($name in @('host-run.ps1','host-identity.ps1')) {
        $origin = Join-Path $Directory ('scripts\' + $name)
        $destination = Join-Path $Root ('private\' + $name)
        if (Test-Path -LiteralPath $destination) {
            if ((Get-FileDigest $destination) -ne (Get-FileDigest $origin)) { throw 'EXISTING_HOST_RUNNER_CHANGED_REVIEW_REQUIRED' }
        } else { [IO.File]::Copy($origin,$destination,$false) }
    }
    $source = $null
    if ($null -ne $saved) { $source = $saved.source_commit } elseif (-not $Resume) { $source = $Bundle.source_commit }
    $deployment = [ordered]@{schema='777-site-deployment-v1';root=$Root;owner_sid=$Site.sid;owner_account=$Site.account;machine=$Site.machine;source_commit=$source;host_order=@('192.168.4.23','192.168.4.38');active_address=$Address;port=$Port;ledger_id=$checked.inventory.ledger_id;certificate_sha256=$checked.certificate_sha256;autostart='not_registered';replication='not_implemented_standby_must_not_write';host_sha256=(Get-FileDigest $native);identity_sha256=(Get-FileDigest (Join-Path $Root 'private\host-identity.ps1'));runner_sha256=(Get-FileDigest (Join-Path $Root 'private\host-run.ps1'))}
    Write-HostJsonNew (Join-Path $Root 'private\deployment.json') $deployment
    return [ordered]@{status='prepared_stopped';root=$Root;ledger_id=$deployment.ledger_id;source_commit=$source;public_connection=(Join-Path $Root 'connection.json');replication=$deployment.replication}
}
