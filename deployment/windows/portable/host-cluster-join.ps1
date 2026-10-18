# A replica uses a fresh local root; existing standalone business data is rejected.
function Join-HostCluster([string] $Directory,$Bundle,$Settings) {
    $site=Assert-HostSetupMachine $Settings
    $root=$Settings.root
    $resume=Test-Path -LiteralPath (Join-Path $root 'private\cluster\config.json')
    $null=Get-LocalHostRoot $root (-not $resume)
    if (-not $resume -and (Test-Path -LiteralPath $root)) { throw 'CLUSTER_JOIN_REQUIRES_NEW_ROOT' }
    Assert-HostBackupLocation $Settings.backup $root
    $native=Join-Path $Directory 'bin\quote-host.exe'
    if ((Get-FileDigest $native) -ne $Bundle.files.'bin/quote-host.exe') { throw 'HOST_PACKAGE_RESOURCE_CHANGED' }
    $capability=Invoke-HostNative $native @('resource-info')
    if ($capability.cluster_protocol -ne '777-cluster-v1') { throw 'REBUILD_HOST_PACKAGE_FOR_CLUSTER' }
    $invitation=Select-HostClusterFile $false
    Write-Host '正在登记并下载初始数据，核对完成后才会启动。较大数据需要等待；中断后使用同一目录再次加入可继续。'
    $null=Invoke-HostNative $native @('cluster-join','--root',$root,'--invitation',$invitation,'--backup-dir',$Settings.backup,'--host',$Settings.address,'--host','127.0.0.1','--host','localhost','--bind',$Settings.address,'--port',[string]$Settings.port,'--worker',(Join-Path $Directory 'bin\quote-ledger.exe'),'--notices',(Join-Path $Directory 'THIRD_PARTY_NOTICES.md'))
    $cluster=Complete-HostClusterDeployment $Directory $Bundle $Settings $site 'replica'
    $null=Invoke-HostSetup $Directory $Bundle $Settings
    Write-Host ('已加入同一账本：'+$cluster.ledger_id) -ForegroundColor Green
    Write-Host ('本机节点：'+$cluster.node_id)
    Write-Host '后台会持续同步；业务请求交由主机处理。主机断线时暂停接单，不自动升主。'
}
function Show-HostClusterStatus($Settings) {
    $native=Join-Path $Settings.root 'private\rust-service-host.exe'
    $state=Invoke-HostNative $native @('cluster-status','--root',$Settings.root)
    if ($state.PSObject.Properties.Name -notcontains 'role') { Write-Host '当前后台尚未启用主机间同步。'; return }
    Write-Host ('角色：'+$state.role+'；账本：'+$state.ledger_id)
    Write-Host ('节点：'+$state.node_id)
    $phases=@{primary='主机';snapshot_failed='生成同步数据失败，请查看日志';joining='加入中';catching_up='追赶数据';synced='已同步';disconnected='断线，等待重连';revoked='已撤销';contact_not_confirmed='尚未确认最新连接'}
    $phase=[string]$state.state.phase
    $label=if ($phases.ContainsKey($phase)) { $phases[$phase] } else { $phase }
    Write-Host ('同步状态：'+$label)
    if ($null -ne $state.current) { Write-Host ('已发布完整数据代：'+$state.current.generation) }
    if ($state.role -eq 'primary') {
        foreach ($peer in $state.peers) {
            $seen=if ($peer.last_seen -gt 0) { [DateTimeOffset]::FromUnixTimeSeconds([long]$peer.last_seen).ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss') } else { '尚未联系' }
            Write-Host ('节点 '+$peer.node_id+'；启用 '+$peer.enabled+'；已确认代 '+$peer.generation+'；上次联系 '+$seen)
        }
    }
    Write-Host '保存成功表示主机已落盘；从机随后同步。此版本不自动故障接管。'
}
function Revoke-HostClusterPeer($Settings) {
    Show-HostClusterStatus $Settings
    $node=Read-Host '输入需要撤销的完整节点ID'
    $parsed=[Guid]::Empty
    if (-not [Guid]::TryParse($node,[ref]$parsed)) { throw 'CLUSTER_NODE_ID_INVALID' }
    $password=$null
    try {
        $password=Read-HostBusinessPassword $false
        $null=Invoke-HostNative (Join-Path $Settings.root 'private\rust-service-host.exe') @('cluster-revoke','--root',$Settings.root,'--admin',$Settings.admin,'--node-id',$node) $password
        Write-Host '节点已撤销，新的同步和业务转发请求会被主机拒绝。'
    } finally { $password=$null }
}
