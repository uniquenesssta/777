# Offline packages do not invent a ledger id. Select only a single owned deployment;
# the native join verifies the actual ledger and business certificate after contact.
function Find-LocalSignedDeployment($Package) {
    $tasks = @(Get-ScheduledTask -TaskName 'Quote777-Host-*' -ErrorAction SilentlyContinue)
    if (-not $tasks.Count) { return $null }
    if ($tasks.Count -ne 1) { throw 'EXISTING_LEDGER_CONFLICT' }
    $task = $tasks[0]
    if ($task.Actions.Count -ne 1 -or $task.Actions[0].Arguments -notmatch '-Root "([^"]+)"') { throw 'HOST_TASK_OWNERSHIP_CONFLICT' }
    $root = Assert-AutomaticLocalPath $Matches[1]
    $directory = Join-Path ([IO.Path]::GetDirectoryName($root)) 'Quote777Host'
    $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if ($task.Description.StartsWith('777-automatic-host-task-v1:')) {
        $m = Get-Content -LiteralPath (Join-Path $directory 'install.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $taskId = if ($m.PSObject.Properties.Name -contains 'task_id') { $m.task_id } else { $m.ledger_id }
        if ($taskId -notmatch '^[a-f0-9-]{36}$' -or $task.TaskName -ne ('Quote777-Host-'+$taskId) -or $task.Description -ne ('777-automatic-host-task-v1:'+$taskId+':S-1-5-18') -or $m.root -ine $root -or $task.Principal.UserId -notin @('SYSTEM','S-1-5-18','NT AUTHORITY\SYSTEM')) { throw 'HOST_TASK_OWNERSHIP_CONFLICT' }
        if ($m.PSObject.Properties.Name -contains 'issuer_id' -and $m.issuer_id -ne $Package.manifest.issuer_id) { throw 'HOST_TRUST_IDENTITY_CONFLICT' }
        $runner = Join-Path $directory 'node-run.ps1'
        if ($task.Actions[0].Execute -ine $shell -or $task.Actions[0].Arguments -cne ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$runner+'" -Root "'+$root+'"')) { throw 'HOST_TASK_ACTION_CONFLICT' }
        return @{root=$root;task=$task;automatic=$true;ledger_id=$m.ledger_id;site_id=$m.site_id;task_id=$taskId}
    }
    $d = Get-HostDeployment $root (Get-FileDigest (Join-Path $PSScriptRoot 'quote-host.exe')) (Get-FileDigest (Join-Path $PSScriptRoot 'node-run.ps1'))
    if ($task.TaskName -ne ('Quote777-Host-'+$d.ledger_id) -or $task.Description -ne ('777-host-task-v1:'+$d.ledger_id+':'+$d.owner_sid)) { throw 'HOST_TASK_OWNERSHIP_CONFLICT' }
    $runner = Join-Path $root 'private\host-run.ps1'
    if ($task.Actions[0].Execute -ine $shell -or $task.Actions[0].Arguments -cne ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$runner+'" -Root "'+$root+'"')) { throw 'HOST_TASK_ACTION_CONFLICT' }
    $cluster = Get-Content -LiteralPath (Join-Path $root 'private\cluster\config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cluster.ledger_id -ne $d.ledger_id -or $cluster.primary.url -ne 'https://192.168.4.23:8477') { throw 'CLUSTER_IDENTITY_CONFLICT' }
    return @{root=$root;task=$task;automatic=$false;deployment=$d;role=$cluster.role;ledger_id=$d.ledger_id;site_id=$null;task_id=$d.ledger_id}
}
