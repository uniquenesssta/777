param([string]$Modules, [string]$Case, [string]$Base)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
foreach ($file in @('host-registration-firewall.ps1','host-registration.ps1','host-setup.ps1')) { . (Join-Path $Modules $file) }
$script:events=@(); $script:created=0; $script:stops=0; $script:updates=0; $script:starts=0
$root=Join-Path $Base 'service'
$program=Join-Path $root 'private\rust-service-host.exe'
$description='777-registration-v1:test-ledger:test-owner'
function Reset-Rule {
    $script:rule=[pscustomobject]@{Description=$description;Action='Allow';Direction='Inbound';Enabled='True';Profile='Domain, Private'}
    $script:ports=[pscustomobject]@{LocalPort='8479';Protocol='TCP'}
    $script:app=[pscustomobject]@{Program=$program}
    $script:addresses=[pscustomobject]@{RemoteAddress='LocalSubnet'}
}
function Write-HostEvent($Event,$Fields) { $script:events+=@{event=$Event;fields=$Fields} }
function Get-NetFirewallRule { [CmdletBinding()]param($Name) return $script:rule }
function Get-NetFirewallPortFilter { [CmdletBinding()]param([Parameter(ValueFromPipeline=$true)]$InputObject) return $script:ports }
function Get-NetFirewallApplicationFilter { [CmdletBinding()]param([Parameter(ValueFromPipeline=$true)]$InputObject) return $script:app }
function Get-NetFirewallAddressFilter { [CmdletBinding()]param([Parameter(ValueFromPipeline=$true)]$InputObject) return $script:addresses }
function New-NetFirewallRule {
    [CmdletBinding()]param($Name,$Description,$DisplayName,$Direction,$Action,$Enabled,$Protocol,$LocalPort,$Program,$RemoteAddress,$Profile)
    if ($Case -eq 'creation-failure') { throw 'SYNTHETIC_FIREWALL_DENIED' }
    if ($Name -ne 'Quote777-Registration-test-ledger' -or $Description -ne $script:description -or $DisplayName -ne $Name -or $Direction -ne 'Inbound' -or $Action -ne 'Allow' -or $Enabled -ne 'True' -or $Protocol -ne 'TCP' -or $LocalPort -ne 8479 -or $Program -ne $script:program -or $RemoteAddress -ne 'LocalSubnet' -or ($Profile -join ',') -ne 'Domain,Private') { throw 'UNEXPECTED_FIREWALL_SCOPE' }
    $script:created++; Reset-Rule
}
function Get-HostDeployment($Root,$Candidate) { return @{ledger_id='test-ledger';owner_sid='test-owner';active_address='192.168.4.23';port=8477} }
function Stop-HostForClusterUpgrade($Directory,$Root) { $script:stops++; $script:state='Disabled' }
function Invoke-HostNative($Native,$Arguments) { $script:updates++ }
function Assert-HostSetupMachine($Settings) { return @{} }
function Test-HostElevated { return $true }
function Set-HostDeploymentVisibility($Directory,$Settings) {}
function Get-HostConnectionCheck($Directory,$Settings) { return @{tcp=$true;https='verified_response';http_status=401} }
function Invoke-HostTaskOperation($Directory,$Root,$Operation) {
    switch ($Operation) {
        'status' { return @{state=$script:state} }
        'start' { $script:starts++; $script:state='Running' }
        default { throw 'UNEXPECTED_TASK_OPERATION' }
    }
}
$bundle=[pscustomobject]@{files=[pscustomobject]@{'host-trust.json'='synthetic';'bin/quote-host.exe'='synthetic'}}
$settings=@{root=$root;address='192.168.4.23';port=8477}
Reset-Rule
switch ($Case) {
    'equivalent' {
        # The original direct RemoteAddress[0] fails for this scalar representation.
        Assert-HostRegistrationFirewall $rule 'test' $description $program
        $addresses.RemoteAddress=@('LocalSubnet'); $ports.LocalPort=@('8479')
        Assert-HostRegistrationFirewall $rule 'test' $description $program
        $ports.Protocol=6; $rule.Profile=3; $app.Program=$program.Replace('\','/').ToUpperInvariant()
        Assert-HostRegistrationFirewall $rule 'test' $description $program
        if ($created) { throw 'REUSED_RULE_WAS_REPLACED' }
    }
    'conflicts' {
        $cases=@(
            @('rule','Description','other-owner','description'),
            @('ports','LocalPort','8477','local_port'),
            @('ports','Protocol','UDP','protocol'),
            @('app','Program','C:\other.exe','program'),
            @('addresses','RemoteAddress','Any','remote_address'),
            @('addresses','RemoteAddress',@('LocalSubnet','Internet'),'remote_count'),
            @('rule','Action','Block','action'),
            @('rule','Direction','Outbound','direction'),
            @('rule','Enabled','False','enabled'),
            @('rule','Profile','Any','profile')
        )
        foreach ($item in $cases) {
            Reset-Rule; $script:events=@()
            $object=Get-Variable -Name $item[0] -Scope Script -ValueOnly
            $object.($item[1])=$item[2]
            try { Update-HostRegistration $Base $bundle $settings; throw 'CONFLICT_ACCEPTED' }
            catch { if ($_.Exception.Message -ne 'REGISTRATION_FIREWALL_OWNERSHIP_CONFLICT') { throw } }
            $last=$events[-1]
            if ($last.event -ne 'host.registration.firewall.conflict' -or @($last.fields.differences | Where-Object { $_.field -eq $item[3] }).Count -ne 1) { throw 'DIFFERENCE_NOT_LOGGED' }
        }
        if ($stops -or $updates -or $created) { throw 'CONFLICT_MUTATED_HOST' }
    }
    'duplicate' {
        $script:rule=@($rule,$rule)
        try { Update-HostRegistration $Base $bundle $settings; throw 'DUPLICATE_ACCEPTED' }
        catch { if ($_.Exception.Message -ne 'REGISTRATION_FIREWALL_OWNERSHIP_CONFLICT') { throw } }
        if ($stops -or $updates -or $created -or $events[-1].fields.field -ne 'rule_count') { throw 'DUPLICATE_NOT_ISOLATED' }
    }
    'create-reuse' {
        $script:rule=$null
        Update-HostRegistration $Base $bundle $settings
        Update-HostRegistration $Base $bundle $settings
        if ($created -ne 1 -or $updates -ne 2 -or $stops -ne 2) { throw 'UPDATE_NOT_REPEATABLE' }
        if ($events[0].event -ne 'host.registration.firewall.verified') { throw 'PREFLIGHT_NOT_FIRST' }
    }
    'creation-failure' {
        $script:rule=$null
        try { Update-HostRegistration $Base $bundle $settings; throw 'CREATION_FAILURE_IGNORED' }
        catch { if ($_.Exception.Message -ne 'SYNTHETIC_FIREWALL_DENIED') { throw } }
        if ($stops -or $updates) { throw 'CREATION_FAILURE_STOPPED_HOST' }
    }
    'resume-setup' {
        [IO.Directory]::CreateDirectory((Join-Path $root 'private')) | Out-Null
        [IO.File]::WriteAllText((Join-Path $root 'private\deployment.json'),'{}')
        $script:state='Disabled'
        $null=Invoke-HostSetup $Base $bundle $settings
        $null=Invoke-HostSetup $Base $bundle $settings
        if ($state -ne 'Running' -or $starts -ne 2 -or $updates -ne 2 -or $created) { throw 'EXISTING_HOST_NOT_RESUMED' }
    }
    default { throw 'UNKNOWN_TEST_CASE' }
}
@{status='passed';case=$Case} | ConvertTo-Json -Compress
