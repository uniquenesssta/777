# Compare firewall semantics, not PowerShell's scalar/array or enum presentation.
function Get-HostRegistrationFirewallState($Rule) {
    $ports = $Rule | Get-NetFirewallPortFilter -ErrorAction Stop
    $app = $Rule | Get-NetFirewallApplicationFilter -ErrorAction Stop
    $addresses = $Rule | Get-NetFirewallAddressFilter -ErrorAction Stop
    $protocol = ([string]$ports.Protocol).Trim().ToUpperInvariant()
    if ($protocol -eq '6') { $protocol = 'TCP' }
    $remote = @($addresses.RemoteAddress | ForEach-Object { ([string]$_).Trim() })
    $profile = ([string]$Rule.Profile).Trim()
    if ($profile -eq '3') { $profile = 'Domain,Private' }
    $profile = (@($profile.Split(',') | ForEach-Object { $_.Trim() } | Sort-Object) -join ',')
    return [ordered]@{
        description = [string]$Rule.Description
        local_port = (@($ports.LocalPort) -join ',')
        protocol = $protocol
        program = ([string]$app.Program).Replace('/', '\')
        remote_address = ($remote -join ',')
        remote_count = $remote.Count
        action = [string]$Rule.Action
        direction = [string]$Rule.Direction
        enabled = [string]$Rule.Enabled
        profile = $profile
    }
}

function Assert-HostRegistrationFirewall($Rule, [string]$Name, [string]$Description, [string]$Program) {
    $rules = @($Rule)
    if ($rules.Count -ne 1) {
        Write-HostEvent 'host.registration.firewall.conflict' @{rule=$Name;field='rule_count';expected=1;actual=$rules.Count}
        throw 'REGISTRATION_FIREWALL_OWNERSHIP_CONFLICT'
    }
    $actual = Get-HostRegistrationFirewallState $rules[0]
    $expected = [ordered]@{description=$Description;local_port='8479';protocol='TCP';program=$Program.Replace('/', '\');remote_address='LocalSubnet';remote_count=1;action='Allow';direction='Inbound';enabled='True';profile='Domain,Private'}
    $differences = @()
    foreach ($field in $expected.Keys) {
        if (-not [string]::Equals([string]$actual[$field], [string]$expected[$field], [StringComparison]::OrdinalIgnoreCase)) {
            $differences += @{field=$field;expected=$expected[$field];actual=$actual[$field]}
        }
    }
    if ($differences.Count) {
        # Only bounded firewall metadata; never serialize the whole CIM object.
        Write-HostEvent 'host.registration.firewall.conflict' @{rule=$Name;differences=$differences}
        throw 'REGISTRATION_FIREWALL_OWNERSHIP_CONFLICT'
    }
}

function Initialize-HostRegistrationFirewall($Deployment, [string]$Root) {
    $name = 'Quote777-Registration-' + $Deployment.ledger_id
    $program = Join-Path $Root 'private\rust-service-host.exe'
    $description = '777-registration-v1:' + $Deployment.ledger_id + ':' + $Deployment.owner_sid
    $rule = Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue
    if ($null -eq $rule) {
        New-NetFirewallRule -Name $name -Description $description -DisplayName $name -Direction Inbound -Action Allow -Enabled True -Protocol TCP -LocalPort 8479 -Program $program -RemoteAddress LocalSubnet -Profile Domain,Private -ErrorAction Stop | Out-Null
        $rule = Get-NetFirewallRule -Name $name -ErrorAction Stop
    }
    Assert-HostRegistrationFirewall $rule $name $description $program
    Write-HostEvent 'host.registration.firewall.verified' @{rule=$name}
}
