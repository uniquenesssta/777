param([string] $Root,[string] $Rule,[string] $UpgradeId,[string] $Directory)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if ($UpgradeId -notmatch '^[a-f0-9-]{36}$' -or $Rule -ne ('Quote777-Pairing-'+$UpgradeId)) { exit 1 }
$deadline=[DateTime]::UtcNow.AddMinutes(30)
$done=Join-Path $Root ('private\automatic-pair-'+$UpgradeId+'.done')
do {
    if (Test-Path -LiteralPath $done) { break }
    Start-Sleep -Seconds 5
} while ([DateTime]::UtcNow -lt $deadline)
$rule=Get-NetFirewallRule -Name $Rule -ErrorAction SilentlyContinue
if ($null -ne $rule -and $rule.Description -eq ('777-pairing:'+$UpgradeId)) { Remove-NetFirewallRule -Name $Rule }
# Only sensitive material belonging to this prepared upgrade is removed.
$path=Join-Path $Directory 'upgrade.json'
if (Test-Path -LiteralPath $path) {
    $value=Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($value.upgrade_id -eq $UpgradeId) { Remove-Item -LiteralPath $path }
}
