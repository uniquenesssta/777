# Repeatable setup: existing ledgers and running tasks are reused, never reset.
function Invoke-HostSetup([string] $Directory, $Bundle, $Settings) {
    $site = Assert-HostSetupMachine $Settings
    if (-not (Test-HostElevated)) { throw 'ELEVATED_WINDOWS_DEPLOYMENT_SHELL_REQUIRED' }
    $manifest = Join-Path $Settings.root 'private\deployment.json'
    $password = $null
    if (Test-Path -LiteralPath $manifest) {
        $deployment = Get-HostDeployment $Settings.root
        if ($deployment.active_address -ne $Settings.address -or $deployment.port -ne $Settings.port) { throw 'EXISTING_HOST_ENDPOINT_CONFLICT' }
        Write-HostEvent 'host.setup.reuse' @{ledger_id=$deployment.ledger_id}
    } else {
        $resume = Test-Path -LiteralPath $Settings.root
        $root = Get-LocalHostRoot $Settings.root (-not $resume)
        Assert-HostBackupLocation $Settings.backup $root
        Assert-HostBackupLocation $Settings.hidden $root
        if ($resume -and (-not (Test-Path -LiteralPath (Join-Path $root 'private\service.json')) -or
            -not (Test-Path -LiteralPath (Join-Path $root 'private\rust-service-host.exe')))) { throw 'EXISTING_DIRECTORY_IS_NOT_A_PREPARED_HOST' }
        try {
            $password = Read-HostBusinessPassword (-not $resume)
            $null = Invoke-HostPreparation $site $Bundle $Directory $root $Settings.backup $Settings.hidden $Settings.admin $password $Settings.address $Settings.port $Settings.hour $resume
        } finally { $password = $null }
    }
    Update-HostRegistration $Directory $Bundle $Settings
    $state = Invoke-HostTaskOperation $Directory $Settings.root 'status'
    if ($state.state -eq 'not_registered') {
        Invoke-HostTaskOperation $Directory $Settings.root 'install'
        $state = Invoke-HostTaskOperation $Directory $Settings.root 'status'
        if ($state.state -eq 'not_registered') { throw 'HOST_TASK_NOT_REGISTERED' }
    }
    if ($state.state -ne 'Running') { Invoke-HostTaskOperation $Directory $Settings.root 'start' }
    # Poll quietly, log the final result once. Running alone is not readiness.
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $check = Get-HostConnectionCheck $Directory $Settings
        if ($check.https -eq 'verified_response') { break }
        if ([DateTime]::UtcNow -ge $deadline) { throw 'HOST_HTTPS_NOT_READY_CHECK_LOGS' }
        Start-Sleep -Milliseconds 1000
    } while ($true)
    Set-HostDeploymentVisibility $Directory $Settings
    Write-HostEvent 'host.setup.finish' @{tcp=$check.tcp;https=$check.https;http_status=$check.http_status}
    return $check
}
