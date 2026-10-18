# Display fixed locations; only multiple local interfaces require a choice.
function Show-HostSetupPaths($Settings) {
    Write-Host ('业务数据目录：'+$Settings.root)
    Write-Host ('普通备份目录：'+$Settings.backup)
    Write-Host ('固定隐藏备份：'+$Settings.hidden)
}
function Select-HostSetupSettings($Settings,[bool] $Joining=$false) {
    $value=$Settings | ConvertTo-Json -Depth 10 | ConvertFrom-Json
    if ($Joining) { Write-Host '将当前电脑加入现有业务数据，目录自动放在程序包旁边。' }
    else { Write-Host '部署会在当前电脑创建独立后台；如要使用同一份数据，请选择菜单10“加入现有数据”。' }
    Show-HostSetupPaths $value
    if (Test-Path -LiteralPath (Join-Path $value.root 'private\service.json')) {
        Write-Host '已找到现有后台，将沿用它的地址、目录和账本。'
        return Get-PreparedHostSettings $value.root $value
    }
    $site=Get-LocalHostInventory
    $candidates=@(Get-HostCandidateAddresses $site.addresses)
    if (-not $candidates.Count) { throw 'NO_LOCAL_LAN_ADDRESS_AVAILABLE' }
    $index=0
    if ($candidates.Count -gt 1) {
        for ($i=0;$i -lt $candidates.Count;$i++) { Write-Host (([string]($i+1))+': '+$candidates[$i]) }
        $choice=Read-Host '选择本机服务地址编号，回车使用1'
        if ($choice) {
            $number=0
            if (-not [int]::TryParse($choice,[ref]$number) -or $number -lt 1 -or $number -gt $candidates.Count) { throw 'LOCAL_HOST_ADDRESS_SELECTION_REQUIRED' }
            $index=$number-1
        }
    }
    $value.address=$candidates[$index]
    Write-Host ('本机服务地址：'+$value.address)
    $value.root=Get-LocalHostRoot $value.root $true
    Assert-HostBackupLocation $value.backup $value.root
    $value.configured=$true
    return $value
}
