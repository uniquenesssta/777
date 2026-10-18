# Read-only network checks. Never disables certificate verification or logs responses/tokens.
function Get-HostConnectionCheck([string] $Directory, $Settings) {
    if (-not ('Quote777.HostProbe' -as [type])) { Add-Type -Path (Join-Path $Directory 'scripts\HostProbe.cs') }
    $origin = 'https://' + $Settings.address + ':' + $Settings.port
    $pin = $null
    $connectionFile = Join-Path $Settings.root 'connection.json'
    if (-not (Test-Path -LiteralPath $connectionFile)) { $connectionFile = Join-Path $Directory 'connection.json' }
    if (Test-Path -LiteralPath $connectionFile) {
        if ((Get-Item -LiteralPath $connectionFile).Length -gt 65536) { throw 'PUBLIC_CONNECTION_TOO_LARGE' }
        $public = Get-Content -LiteralPath $connectionFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($public.schema -ne '777-public-connection-v1' -or $public.connection.url.TrimEnd('/') -ne $origin) { throw 'HOST_PUBLIC_CONNECTION_CONFLICT' }
        $pin = $public.connection.certificate_sha256
    }
    $probe = [Quote777.HostProbe]::Check($origin, $pin)
    return [ordered]@{address=$Settings.address;port=$Settings.port;tcp=$probe.Tcp;https=$probe.Https;http_status=$probe.HttpStatus;error=$probe.Error;business_access='not_checked'}
}
