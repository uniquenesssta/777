# Explicit controlled upgrade, retaining the existing ledger, TLS identity and task.
function Stop-HostForClusterUpgrade([string] $Directory,[string] $Root) {
    $state=Invoke-HostTaskOperation $Directory $Root 'status'
    if ($state.state -eq 'not_registered') { return }
    Invoke-HostTaskOperation $Directory $Root 'stop'
    $deadline=[DateTime]::UtcNow.AddSeconds(90)
    do {
        $state=Invoke-HostTaskOperation $Directory $Root 'status'
        if ($state.state -ne 'Running') { break }
        if ([DateTime]::UtcNow -ge $deadline) { throw 'HOST_NOT_STOPPED_UPGRADE_DEFERRED' }
        Start-Sleep -Milliseconds 1000
    } while ($true)
    # The native command must also obtain the ledger's exclusive process lock.
}
function Enable-HostCluster([string] $Directory,$Bundle,$Settings) {
    $site=Assert-HostSetupMachine $Settings
    $root=$Settings.root
    if (-not (Test-Path -LiteralPath (Join-Path $root 'private\deployment.json'))) { throw 'PREPARE_EXISTING_PRIMARY_FIRST' }
    $candidate=Join-Path $Directory 'bin\quote-host.exe'
    $candidateHash=$Bundle.files.'bin/quote-host.exe'
    if ((Get-FileDigest $candidate) -ne $candidateHash) { throw 'HOST_PACKAGE_RESOURCE_CHANGED' }
    $capability=Invoke-HostNative $candidate @('resource-info')
    if ($capability.cluster_protocol -ne '777-cluster-v1') { throw 'REBUILD_HOST_PACKAGE_FOR_CLUSTER' }
    # The candidate exception only permits this exact, package-verified host hash.
    # This allows an authenticated retry if power failed after native selection.
    $deployment=Get-HostDeployment $root $candidateHash
    $native=Join-Path $root 'private\rust-service-host.exe'
    if ((Get-FileDigest $native) -eq $deployment.host_sha256) { Stop-HostForClusterUpgrade $Directory $root }
    $password=$null
    try {
        Write-Host '请输入现有账本访问密码。服务正常停止后升级，账本和证书保留。'
        $password=Read-HostBusinessPassword $false
        $null=Invoke-HostNative $candidate @('select-host','--root',$root,'--admin',$Settings.admin,'--backend','rust','--worker',(Join-Path $Directory 'bin\quote-ledger.exe'),'--notices',(Join-Path $Directory 'THIRD_PARTY_NOTICES.md'),'--upgrade-resources') $password
        $checked=Invoke-HostNative $native @('inspect','--root',$root)
        if ($checked.inventory.ledger_id -ne $deployment.ledger_id -or $checked.certificate_sha256 -ne $deployment.certificate_sha256) { throw 'CLUSTER_UPGRADE_IDENTITY_CONFLICT' }
        $deployment.host_sha256=Get-FileDigest $native
        $deployment.source_commit=$Bundle.source_commit
        Write-HostJsonReplace (Join-Path $root 'private\deployment.json') $deployment
        $null=Invoke-HostNative $native @('cluster-primary','--root',$root,'--admin',$Settings.admin) $password
        $null=Complete-HostClusterDeployment $Directory $Bundle $Settings $site 'primary'
    } finally { $password=$null }
    $null=Invoke-HostSetup $Directory $Bundle $Settings
    Write-Host '主机同步已启用。可选择“导出加入文件”，供另一台电脑加入。' -ForegroundColor Green
}
function Export-HostClusterInvitation([string] $Directory,$Settings) {
    $destination=Select-HostClusterFile $true
    $password=$null; $invitation=$null
    try {
        $password=Read-HostBusinessPassword $false
        $invitation=Invoke-HostNative (Join-Path $Settings.root 'private\rust-service-host.exe') @('cluster-invite','--root',$Settings.root,'--admin',$Settings.admin) $password
        Write-HostJsonNew $destination $invitation
        Write-Host ('已保存：'+$destination)
        Write-Host '此文件30分钟内有效，只能登记一台新电脑。复制给目标电脑后，选择“加入现有数据”；完成后可删除此文件。'
    } finally { $password=$null; $invitation=$null }
}
