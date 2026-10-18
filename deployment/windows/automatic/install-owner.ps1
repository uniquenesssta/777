# Recognize only an existing task and deployment owned by this package's ledger.
function Find-AutomaticDeployment($Package) {
    $ledger=[string]$Package.manifest.ledger_id
    $task=Get-ScheduledTask -TaskName ('Quote777-Host-'+$ledger) -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        if (@(Get-ScheduledTask -TaskName 'Quote777-Host-*' -ErrorAction SilentlyContinue).Count) { throw 'EXISTING_LEDGER_CONFLICT' }
        return $null
    }
    if ($task.Actions.Count -ne 1 -or $task.Actions[0].Arguments -notmatch '-Root "([^"]+)"') { throw 'HOST_TASK_OWNERSHIP_CONFLICT' }
    $root=Assert-AutomaticLocalPath $Matches[1]
    if ($task.Description.StartsWith('777-automatic-host-task-v1:'+ $ledger+':')) {
        $marker=Join-Path ([IO.Path]::GetDirectoryName($root)) 'Quote777Host\install.json'
        $m=Get-Content -LiteralPath $marker -Raw -Encoding UTF8|ConvertFrom-Json
        if ($m.ledger_id -ne $ledger -or $m.site_id -ne $Package.manifest.site_id -or $m.root -ine $root -or $task.Principal.UserId -notin @('SYSTEM','S-1-5-18','NT AUTHORITY\SYSTEM')) { throw 'HOST_TASK_OWNERSHIP_CONFLICT' }
        $runner=Join-Path ([IO.Path]::GetDirectoryName($root)) 'Quote777Host\node-run.ps1'
        $shell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        if ($task.Actions[0].Execute -ine $shell -or $task.Actions[0].Arguments -cne ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$runner+'" -Root "'+$root+'"')) { throw 'HOST_TASK_ACTION_CONFLICT' }
        return @{root=$root;task=$task;automatic=$true}
    }
    $d=Get-HostDeployment $root (Get-FileDigest (Join-Path $PSScriptRoot 'quote-host.exe')) (Get-FileDigest (Join-Path $PSScriptRoot 'node-run.ps1'))
    if ($d.ledger_id -ne $ledger -or $task.Description -cne ('777-host-task-v1:'+ $ledger+':'+$d.owner_sid)) { throw 'HOST_TASK_OWNERSHIP_CONFLICT' }
    $shell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $args='-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $root 'private\host-run.ps1')+'" -Root "'+$root+'"'
    if ($task.Actions[0].Execute -ine $shell -or $task.Actions[0].Arguments -cne $args) { throw 'HOST_TASK_ACTION_CONFLICT' }
    $cluster=Get-Content -LiteralPath (Join-Path $root 'private\cluster\config.json') -Raw -Encoding UTF8|ConvertFrom-Json
    if ($cluster.ledger_id -ne $ledger -or $cluster.primary.certificate_sha256 -ne $Package.profile.tls.certificate_sha256) { throw 'CLUSTER_IDENTITY_CONFLICT' }
    return @{root=$root;task=$task;automatic=$false;deployment=$d;role=$cluster.role}
}
function Stop-AutomaticOwnedTask($Existing) {
    Disable-ScheduledTask -TaskName $Existing.task.TaskName|Out-Null
    if ($Existing.task.State -eq 'Running') {
        $stop=if ($Existing.automatic) { Join-Path ([IO.Path]::GetDirectoryName($Existing.root)) 'Quote777Host\stop.request' } else { Join-Path $Existing.root 'private\stop.request' }
        [IO.File]::WriteAllText($stop,'stop')
        $deadline=[DateTime]::UtcNow.AddSeconds(60)
        do {
            Start-Sleep -Milliseconds 500
            $task=Get-ScheduledTask -TaskName $Existing.task.TaskName
            if ([DateTime]::UtcNow -gt $deadline) { throw 'HOST_GRACEFUL_STOP_TIMED_OUT' }
        } while ($task.State -eq 'Running')
    }
}
