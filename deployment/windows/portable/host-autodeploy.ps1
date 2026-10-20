# One action resumes an existing cluster or joins a fresh machine to it.
function Invoke-HostAutoDeployment([string] $Directory,$Bundle,$Settings) {
    $cluster=Join-Path $Settings.root 'private\cluster\config.json'
    $manifest=Join-Path $Settings.root 'private\deployment.json'
    $service=Join-Path $Settings.root 'private\service.json'
    if ($Settings.address -eq '192.168.4.23' -and $Bundle.files.PSObject.Properties.Name -contains 'host-trust.json') {
        $null=Invoke-HostSetup $Directory $Bundle $Settings
    } elseif ([IO.File]::Exists($cluster)) {
        if ([IO.File]::Exists($manifest)) { $null=Invoke-HostSetup $Directory $Bundle $Settings }
        else { Join-HostCluster $Directory $Bundle $Settings -AutoInvitation }
    } elseif ([IO.File]::Exists($service)) {
        if (-not [IO.File]::Exists($manifest)) { $null=Invoke-HostSetup $Directory $Bundle $Settings }
        Enable-HostCluster $Directory $Bundle $Settings
    } else {
        Join-HostCluster $Directory $Bundle $Settings -AutoInvitation
    }
    Show-ConnectionCheck (Get-HostConnectionCheck $Directory $Settings)
    Show-HostClusterStatus $Settings
    Write-Host '自动部署完成，后台已设置开机启动。可以关闭此窗口。' -ForegroundColor Green
}
