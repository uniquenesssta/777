param(
    [ValidateSet('menu','setup','check','start','stop','logs','inventory','settings','cluster-primary','cluster-invite','cluster-join','cluster-status','cluster-revoke')][string] $Action='menu',
    [string] $ExpectedSid, [string] $LogSession,
    [switch] $NoPause
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
if ($env:OS -ne 'Windows_NT') { throw 'WINDOWS_DEPLOYMENT_REQUIRED' }
foreach ($name in @('host-identity.ps1','host-log.ps1','host-package.ps1','host-site.ps1','host-paths.ps1','host-native.ps1','host-prepare.ps1','host-access.ps1','host-settings.ps1','host-options.ps1','host-setup.ps1','host-check.ps1','host-cluster-files.ps1','host-cluster-primary.ps1','host-cluster-join.ps1')) { . (Join-Path $PSScriptRoot ('scripts\' + $name)) }

function Show-ConsoleFailure($Failure) {
    $code = $Failure.Exception.Message
    if ($code -notmatch '^[A-Z][A-Z0-9_]{4,100}$') { $code='WINDOWS_HOST_DEPLOYMENT_FAILED' }
    Write-HostEvent 'host.console.failed' @{operation=$script:SelectedAction;error=$code;hresult=$Failure.Exception.HResult}
    Write-Host ('操作未完成：' + $code) -ForegroundColor Red
    Write-Host '已有数据已保留。请打开日志，将本次 runtime.jsonl 提供给维护人员。'
}
function Show-ConnectionCheck($Check) {
    Write-Host ('服务地址：' + $Check.address + ':' + $Check.port)
    if ($Check.tcp) { Write-Host '网络端口：可连接' -ForegroundColor Green }
    else { Write-Host '网络端口：无法连接，请检查主机是否开机、网络和防火墙。' -ForegroundColor Yellow }
    switch ($Check.https) {
        'verified_response' { Write-Host 'HTTPS：证书指纹匹配，后台已响应。' -ForegroundColor Green }
        'public_connection_required' { Write-Host 'HTTPS：尚未检查。可将服务根目录中的公开 connection.json 复制到本包目录后再次检查。' }
        default { Write-Host ('HTTPS：尚未就绪（' + $Check.https + '），请查看日志。') -ForegroundColor Yellow }
    }
    Write-Host '此检查确认网络与服务响应，业务操作和备份结果仍需在软件中确认。'
}
function Invoke-ConsoleAction([string] $Selected) {
    $script:SelectedAction=$Selected
    Write-HostEvent 'host.console.action' @{operation=$Selected}
    if ($Selected -eq 'cluster-join' -and -not (Test-Path -LiteralPath (Join-Path $script:Settings.root 'private\cluster\config.json'))) {
        if (Test-Path -LiteralPath (Join-Path $script:Settings.root 'private\service.json')) {
            $script:Settings.root=Join-Path ([IO.Path]::GetDirectoryName($script:Settings.root)) 'Quote777Replica'
            $script:Settings.configured=$false
        }
        if (-not $script:Settings.configured) { $script:Settings=Select-HostSetupSettings $script:Settings $true }
        Save-HostSetupSettings $PSScriptRoot $script:Settings
    }
    if ($Selected -eq 'setup') {
        if (-not $script:Settings.configured) { $script:Settings=Select-HostSetupSettings $script:Settings }
        Save-HostSetupSettings $PSScriptRoot $script:Settings
    }
    if ($Selected -in @('setup','start','stop','cluster-primary','cluster-join')) {
        $null=Assert-HostSetupMachine $script:Settings
        if (-not (Test-HostElevated)) {
            Write-Host '即将请求管理员权限，请使用当前 Windows 账户。'
            Invoke-HostElevatedConsole $PSScriptRoot $Selected
            return
        }
    }
    switch ($Selected) {
        'cluster-primary' { Enable-HostCluster $PSScriptRoot $script:Bundle $script:Settings }
        'cluster-invite' { Export-HostClusterInvitation $PSScriptRoot $script:Settings }
        'cluster-join' { Join-HostCluster $PSScriptRoot $script:Bundle $script:Settings }
        'cluster-status' { Show-HostClusterStatus $script:Settings }
        'cluster-revoke' { Revoke-HostClusterPeer $script:Settings }
        'setup' {
            Write-Host ('服务根目录：' + $script:Settings.root)
            Write-Host ('普通备份：' + $script:Settings.backup)
            Write-Host ('隐藏备份：' + $script:Settings.hidden)
            Write-Host '已有后台会直接沿用；首次准备才要求业务密码，首次注册自启才要求 Windows 登录密码。'
            $check=Invoke-HostSetup $PSScriptRoot $script:Bundle $script:Settings
            Show-ConnectionCheck $check
        }
        'check' {
            if (Test-Path -LiteralPath (Join-Path $script:Settings.root 'private\deployment.json')) {
                $state=Invoke-HostTaskOperation $PSScriptRoot $script:Settings.root 'status'
                Write-Host ('开机任务：' + $state.state + '；状态码：' + $state.last_task_result)
                if ($state.last_task_result -eq 267009) { Write-Host '267009 表示任务正在运行。' }
            }
            $check=Get-HostConnectionCheck $PSScriptRoot $script:Settings
            Write-HostEvent 'host.check.finish' @{tcp=$check.tcp;https=$check.https;http_status=$check.http_status;error=$check.error}
            Show-ConnectionCheck $check
        }
        'start' {
            $state=Invoke-HostTaskOperation $PSScriptRoot $script:Settings.root 'status'
            if ($state.state -ne 'Running') { Invoke-HostTaskOperation $PSScriptRoot $script:Settings.root 'start' }
            else { Write-Host '后台任务已在运行。' }
            Invoke-ConsoleAction 'check'
        }
        'stop' {
            Invoke-HostTaskOperation $PSScriptRoot $script:Settings.root 'stop'
            Write-Host '已请求正常停止，并暂停开机启动；再次选择“启动后台”会恢复自启。请检查状态后再维护数据。'
        }
        'settings' {
            $script:Settings=Select-HostSetupSettings $script:Settings
            Save-HostSetupSettings $PSScriptRoot $script:Settings
            Write-Host '已保存本机部署位置，选择一键部署时使用。'
        }
        'logs' { Start-Process explorer.exe -ArgumentList (ConvertTo-HostArgument (Join-Path $PSScriptRoot 'logs')) | Out-Null }
        'inventory' {
            $site=Get-LocalHostInventory
            Write-HostEvent 'deployment.inventory' @{machine=$site.machine;os=$site.os;addresses=$site.addresses;account=$site.account;sid=$site.sid}
            Write-Host ('本机地址：' + ($site.addresses -join ', '))
            Write-Host ('Windows 运行账户：' + $site.account)
            Write-Host '采集完成，已写入本次日志。'
        }
    }
}
$script:SelectedAction=$Action
$exitCode=0
try {
    if ($ExpectedSid -and $ExpectedSid -ne [Security.Principal.WindowsIdentity]::GetCurrent().User.Value) { throw 'ELEVATION_MUST_KEEP_ORIGINAL_WINDOWS_ACCOUNT' }
    Start-HostLog $PSScriptRoot $LogSession
    $script:Bundle=Get-HostBundle $PSScriptRoot
    $script:Settings=Get-HostSetupSettings $PSScriptRoot
    Write-Host '777 后台管理'
    Write-Host ('本次日志：' + $script:HostLogDirectory)
    if ($Action -eq 'menu') {
        $choices=@{'1'='setup';'2'='check';'3'='start';'4'='stop';'5'='logs';'6'='inventory';'7'='settings';'8'='cluster-primary';'9'='cluster-invite';'10'='cluster-join';'11'='cluster-status';'12'='cluster-revoke'}
        while ($true) {
            Write-Host ''
            Write-Host '1 一键部署并启动    2 查看状态与连接    3 启动后台'
            Write-Host '4 正常停止后台      5 打开日志文件夹    6 采集主机信息'
            Write-Host '7 选择部署位置      8 将现有后台设为同步主机'
            Write-Host '9 导出加入文件      10 加入现有数据      11 查看同步状态'
            Write-Host '12 撤销同步节点     0 退出'
            $choice=Read-Host '输入数字后按回车'
            if ($choice -eq '0') { break }
            if ($choices.ContainsKey($choice)) {
                try { Invoke-ConsoleAction $choices[$choice] } catch { Show-ConsoleFailure $_ }
            } else { Write-Host '请输入菜单中的数字。' }
        }
    } else { Invoke-ConsoleAction $Action }
} catch { Show-ConsoleFailure $_; $exitCode=1 }
finally {
    Write-HostEvent 'runtime.stop' @{}
    if ($Action -ne 'menu' -and -not $NoPause) { $null=Read-Host '按回车关闭窗口' }
}
exit $exitCode
