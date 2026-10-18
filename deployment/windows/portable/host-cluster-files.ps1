# Public join-file dialogs and atomic, owner-scoped deployment metadata updates.
function Select-HostClusterFile([bool] $Save) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog=if ($Save) { [Windows.Forms.SaveFileDialog]::new() } else { [Windows.Forms.OpenFileDialog]::new() }
    $dialog.Filter='777 join file (*.777join)|*.777join'
    if ($Save) { $dialog.FileName='Quote777.777join'; $dialog.OverwritePrompt=$false }
    $dialog.Title=if ($Save) { '保存一次性加入文件（30分钟有效，每台电脑一份）' } else { '选择主机导出的加入文件' }
    try {
        if ($dialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { throw 'CLUSTER_FILE_SELECTION_CANCELLED' }
        if ($Save -and (Test-Path -LiteralPath $dialog.FileName)) { throw 'CLUSTER_INVITATION_REQUIRES_NEW_FILE' }
        return $dialog.FileName
    } finally { $dialog.Dispose() }
}
function Write-HostJsonReplace([string] $Path,$Value) {
    $temporary=$Path+'.'+[Guid]::NewGuid().ToString('N')+'.partial'
    try {
        [IO.File]::WriteAllText($temporary,($Value | ConvertTo-Json -Depth 30 -Compress),[Text.UTF8Encoding]::new($false))
        if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temporary,$Path,[System.Management.Automation.Language.NullString]::Value) }
        else { [IO.File]::Move($temporary,$Path) }
    } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary } }
}
function Complete-HostClusterDeployment([string] $Directory,$Bundle,$Settings,$Site,[string] $Role) {
    $root=$Settings.root
    $native=Join-Path $root 'private\rust-service-host.exe'
    $checked=Invoke-HostNative $native @('inspect','--root',$root)
    $cluster=Invoke-HostNative $native @('cluster-status','--root',$root)
    if ($cluster.role -ne $Role -or $cluster.ledger_id -ne $checked.inventory.ledger_id) { throw 'CLUSTER_DEPLOYMENT_IDENTITY_CONFLICT' }
    $template=Read-HostSettingsJson (Join-Path $root 'client-template.json')
    $public=[ordered]@{schema='777-public-connection-v1';connection=[ordered]@{url=$template.url;certificate_pem=[IO.File]::ReadAllText((Join-Path $root 'service-cert.pem'));certificate_sha256=$template.certificate_sha256}}
    Write-HostJsonNew (Join-Path $root 'connection.json') $public
    $path=Join-Path $root 'private\deployment.json'
    if (Test-Path -LiteralPath $path) { $deployment=Get-HostDeployment $root }
    else {
        foreach ($name in @('host-run.ps1','host-identity.ps1')) {
            $destination=Join-Path $root ('private\'+$name)
            if (-not (Test-Path -LiteralPath $destination)) { [IO.File]::Copy((Join-Path $Directory ('scripts\'+$name)),$destination,$false) }
            elseif ((Get-FileDigest $destination) -ne (Get-FileDigest (Join-Path $Directory ('scripts\'+$name)))) { throw 'UNOWNED_HOST_RUNNER_CONFLICT' }
        }
        $deployment=[pscustomobject]@{schema='777-site-deployment-v1';root=$root;owner_sid=$Site.sid;owner_account=$Site.account;machine=$Site.machine;source_commit=$Bundle.source_commit;host_order=@($Settings.address);active_address=$Settings.address;port=$Settings.port;ledger_id=$checked.inventory.ledger_id;certificate_sha256=$checked.certificate_sha256;autostart='not_registered';deployment_mode='cluster';replication='primary_async_snapshot_v1';host_sha256=(Get-FileDigest $native);identity_sha256=(Get-FileDigest (Join-Path $root 'private\host-identity.ps1'));runner_sha256=(Get-FileDigest (Join-Path $root 'private\host-run.ps1'))}
    }
    # Early standalone manifests predate deployment_mode. Preserve their owned
    # identity/resources and add only the authenticated cluster metadata.
    $deployment | Add-Member -MemberType NoteProperty -Name deployment_mode -Value 'cluster' -Force
    $deployment | Add-Member -MemberType NoteProperty -Name replication -Value 'primary_async_snapshot_v1' -Force
    Write-HostJsonReplace $path $deployment
    return $cluster
}

# Only look inside this package; never scan or log join-ticket contents.
function Get-HostAutoInvitation([string] $Directory) {
    $files=@(Get-ChildItem -LiteralPath $Directory -Filter '*.777join' -File -Force)
    if ($files.Count -eq 1) { return $files[0].FullName }
    Write-Host '请选择主机导出的加入文件。也可以将唯一的一份加入文件放在程序包中，再双击 deploy.cmd。'
    return Select-HostClusterFile $false
}
