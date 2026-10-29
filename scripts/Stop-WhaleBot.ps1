[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateRange(1, 300)]
    [int]$StopTimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

try {
    $dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($dockerCommand) {
        $dockerExe = $dockerCommand.Source
    } else {
        $dockerPaths = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
            (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
        )
        $dockerExe = $dockerPaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
    if (-not $dockerExe) { throw 'Docker was not found. No containers were changed.' }
    $env:PATH = (Split-Path -Parent $dockerExe) + ';' + $env:PATH

    function Test-DockerEngine {
        $ErrorActionPreference = 'Continue'
        & $dockerExe info --format '{{.OSType}}' 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    }
    Write-Host '[1/2] Checking WhaleBot containers...'
    if (-not (Test-DockerEngine)) {
        throw 'Docker engine is unavailable. If Docker Desktop is closed, the bot is already offline. Otherwise open Docker Desktop and retry.'
    }

    # Use Compose labels so shutdown also works if .env is missing or invalid.
    # Limit the operation to this project and its two application services.
    $containerIds = @(
        foreach ($service in @('astrbot', 'snowluma')) {
            $ids = & $dockerExe ps --quiet --filter 'label=com.docker.compose.project=whalebot' --filter "label=com.docker.compose.service=$service"
            if ($LASTEXITCODE -ne 0) { throw "Could not check $service containers." }
            $ids | Where-Object { $_ }
        }
    )
    if ($containerIds.Count -eq 0) {
        Write-Host 'WhaleBot containers are already stopped.'
        exit 0
    }

    Write-Host '[2/2] Stopping AstrBot and SnowLuma...'
    if ($PSCmdlet.ShouldProcess('WhaleBot application containers', 'Stop containers and keep all data volumes')) {
        & $dockerExe stop --time $StopTimeoutSeconds @containerIds
        if ($LASTEXITCODE -ne 0) { throw 'One or more containers could not be stopped. Check Docker Desktop.' }
        foreach ($containerId in $containerIds) {
            $running = & $dockerExe inspect --format '{{.State.Running}}' $containerId
            if ($LASTEXITCODE -ne 0 -or ($running -join '').Trim() -ne 'false') {
                throw "Could not confirm container $containerId has stopped."
            }
        }
        Write-Host 'WhaleBot stopped. Configuration, chat history and QQ data are preserved.'
        Write-Host 'Double-click Start-WhaleBot.cmd to start again. Docker Desktop remains running.'
    }
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
