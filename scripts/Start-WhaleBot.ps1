param(
    [switch]$NoBrowser,
    [ValidateRange(30, 900)]
    [int]$DockerTimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

try {
    $dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
    $dockerPaths = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
        (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
    )
    if ($dockerCommand) {
        $dockerExe = $dockerCommand.Source
    } else {
        $dockerExe = $dockerPaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
    if (-not $dockerExe) {
        throw 'Docker Desktop was not found. Install Docker Desktop with the WSL2 backend first.'
    }
    # Credential helpers must be available even in terminals opened before installation.
    $env:PATH = (Split-Path -Parent $dockerExe) + ';' + $env:PATH

    function Get-DockerEngineOS {
        # Windows PowerShell 5.1 can treat native stderr as a terminating error.
        $ErrorActionPreference = 'Continue'
        $result = & $dockerExe info --format '{{.OSType}}' 2>$null
        if ($LASTEXITCODE -eq 0) { return ($result -join '').Trim() }
        return $null
    }
    Write-Host '[1/4] Checking Docker...'
    $engineOS = Get-DockerEngineOS
    if (-not $engineOS) {
        $desktopPaths = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),
            (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
        )
        $desktopExe = $desktopPaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $desktopExe) { throw 'Docker engine is stopped and Docker Desktop could not be located.' }
        if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
            Start-Process -FilePath $desktopExe -WindowStyle Hidden
        }
        Write-Host 'Waiting for Docker Desktop. Complete any first-run prompts in Docker Desktop.'
        $timer = [System.Diagnostics.Stopwatch]::StartNew()
        do {
            Start-Sleep -Seconds 3
            $engineOS = Get-DockerEngineOS
            if ($engineOS) { break }
            if ($timer.Elapsed.TotalSeconds -ge $DockerTimeoutSeconds) {
                throw 'Docker did not become ready. Open Docker Desktop, resolve its startup message, then retry.'
            }
        } while ($true)
    }
    if (($engineOS -join '').Trim() -ne 'linux') {
        throw 'Switch Docker Desktop to Linux containers, then retry.'
    }
    & $dockerExe compose version
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose is unavailable. Update Docker Desktop.' }

    Write-Host '[2/4] Checking local configuration...'
    $envPath = Join-Path $projectRoot '.env'
    if (-not (Test-Path -LiteralPath $envPath)) {
        Copy-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Destination $envPath
    }
    $envText = [System.IO.File]::ReadAllText($envPath)
    if ($envText -notmatch '(?m)^\s*VNC_PASSWD\s*=\s*[^\s\r\n]+') {
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $bytes = New-Object byte[] 4
            $rng.GetBytes($bytes)
        } finally { $rng.Dispose() }
        $password = [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
        if ($envText -match '(?m)^\s*VNC_PASSWD\s*=.*$') {
            $envText = [regex]::Replace($envText, '(?m)^\s*VNC_PASSWD\s*=.*$', 'VNC_PASSWD=' + $password)
        } else {
            $envText = $envText.TrimEnd() + "`r`nVNC_PASSWD=$password`r`n"
        }
        [System.IO.File]::WriteAllText($envPath, $envText, [System.Text.UTF8Encoding]::new($false))
        Write-Host 'A private desktop password was saved in .env (VNC_PASSWD).'
    }
    # Keep resolved configuration in memory; it can contain credentials.
    $configJson = & $dockerExe compose config --format json
    if ($LASTEXITCODE -ne 0) { throw 'Invalid Compose configuration. Check .env and compose.yaml.' }
    $config = ($configJson -join "`n") | ConvertFrom-Json

    Write-Host '[3/4] Starting AstrBot and SnowLuma...'
    & $dockerExe compose up -d
    if ($LASTEXITCODE -ne 0) { throw 'Container startup failed. Check Docker connectivity, image tags and port availability.' }

    Write-Host '[4/4] Waiting for local pages...'
    $pages = @(
        @{ Service = 'astrbot'; Target = 6185 },
        @{ Service = 'snowluma'; Target = 5099 },
        @{ Service = 'snowluma'; Target = 6081 }
    )
    $urls = @($pages | ForEach-Object {
        $service = $config.services.PSObject.Properties[$_.Service].Value
        $target = $_.Target
        $port = $service.ports | Where-Object { $_.target -eq $target } | Select-Object -First 1
        if (-not $port) { throw "Missing port mapping for $target." }
        'http://127.0.0.1:' + $port.published + '/'
    })
    $pending = @($urls)
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($pending.Count -gt 0 -and $timer.Elapsed.TotalSeconds -lt 90) {
        $pending = @($pending | Where-Object {
            try {
                $response = Invoke-WebRequest -Uri $_ -UseBasicParsing -TimeoutSec 3
                $response.StatusCode -ne 200
            } catch { $true }
        })
        if ($pending.Count -gt 0) { Start-Sleep -Seconds 2 }
    }
    & $dockerExe compose ps
    if ($pending.Count -gt 0) {
        throw ('Pages did not become ready: ' + ($pending -join ', ') + '. Run docker compose logs --tail 100.')
    }
    Write-Host 'WhaleBot services are ready. QQ may still require login in the desktop.'
    $urls | ForEach-Object { Write-Host $_ }
    if (-not $NoBrowser) {
        foreach ($url in $urls) { Start-Process $url }
    }
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
