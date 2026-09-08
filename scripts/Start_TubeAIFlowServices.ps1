param(
    [Parameter(Mandatory = $true)]
    [int]$BackendPort,
    [int]$FrontendPort = 5173,
    [switch]$Check
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$backendDirectory = Join-Path $root "backend"
$frontendDirectory = Join-Path $root "frontend"
$backendPython = Join-Path $backendDirectory ".venv\Scripts\python.exe"
$workspaceDirectory = Join-Path $backendDirectory "workspace"
$logDirectory = Join-Path $workspaceDirectory "logs"
$statePath = Join-Path $workspaceDirectory "tubeaiflow.processes.json"

function Test-ProcessRunning([int]$ProcessId) {
    return $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Test-PortListening([int]$Port) {
    foreach ($line in & netstat.exe -ano -p tcp) {
        if ($line -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+\d+\s*$") {
            return $true
        }
    }
    return $false
}

function Stop-StartedProcess($Process) {
    if ($null -ne $Process -and -not $Process.HasExited) {
        & taskkill.exe /PID $Process.Id /T /F | Out-Null
    }
}

function Wait-ServiceReady([int]$ApiPort, [int]$WebPort) {
    $deadline = (Get-Date).AddSeconds(90)
    Write-Host 'Waiting for TubeAiFolw services...'
    do {
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/health" -TimeoutSec 2
            $web = Invoke-WebRequest "http://127.0.0.1:$WebPort" -UseBasicParsing -TimeoutSec 2
            if ($health.data.product -eq 'TubeAiFolw' -and $health.data.status -eq 'ok' -and $web.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "Services did not become ready within 90 seconds. See $logDirectory"
}

if (-not (Test-Path -LiteralPath $backendPython)) {
    throw "Backend Python was not found: $backendPython"
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendDirectory "package.json"))) {
    throw "Frontend package.json was not found: $frontendDirectory"
}
if ($Check) {
    Write-Host "[OK] The background service launcher is ready."
    exit 0
}

if (Test-Path -LiteralPath $statePath) {
    $reuse = $false
    try {
        $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
        $backendRunning = Test-ProcessRunning -ProcessId ([int]$state.backend_pid)
        $frontendRunning = Test-ProcessRunning -ProcessId ([int]$state.frontend_pid)
        if ($backendRunning -and $frontendRunning) {
            $reuse = $true
        }
        foreach ($staleProcessId in @([int]$state.frontend_pid, [int]$state.backend_pid)) {
            if ($reuse) { break }
            if (Test-ProcessRunning -ProcessId $staleProcessId) {
                Write-Host "Stopping incomplete process tree $staleProcessId..."
                & taskkill.exe /PID $staleProcessId /T /F | Out-Null
            }
        }
    }
    catch {
        Write-Host "Ignoring a stale process state file."
    }
    if ($reuse) {
        Wait-ServiceReady -ApiPort ([int]$state.backend_port) -WebPort ([int]$state.frontend_port)
        Write-Host 'TubeAiFolw is already running.'
        exit 0
    }
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
}

if (Test-PortListening -Port $FrontendPort) {
    throw "Frontend port $FrontendPort is already in use. Run Restart_TubeAIFlow.bat to clean up the previous instance."
}

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$frontendOutput = Join-Path $logDirectory "frontend.stdout.log"
$frontendError = Join-Path $logDirectory "frontend.stderr.log"
$backendOutput = Join-Path $logDirectory "backend.stdout.log"
$backendError = Join-Path $logDirectory "backend.stderr.log"

$backendProcess = $null
$frontendProcess = $null
try {
    $env:APP_PORT_OVERRIDE = [string]$BackendPort
    $backendProcess = Start-Process `
        -FilePath $backendPython `
        -ArgumentList @("-m", "app.run") `
        -WorkingDirectory $backendDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendOutput `
        -RedirectStandardError $backendError `
        -PassThru

    $env:VITE_API_PORT = [string]$BackendPort
    $frontendProcess = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList @("/d", "/s", "/c", '"npm.cmd run dev"') `
        -WorkingDirectory $frontendDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendOutput `
        -RedirectStandardError $frontendError `
        -PassThru

    Start-Sleep -Milliseconds 800
    if ($backendProcess.HasExited) {
        throw "The backend exited during startup. See $backendError"
    }
    if ($frontendProcess.HasExited) {
        throw "The frontend exited during startup. See $frontendError"
    }

    [ordered]@{
        backend_pid = $backendProcess.Id
        frontend_pid = $frontendProcess.Id
        backend_port = $BackendPort
        frontend_port = $FrontendPort
        started_at = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8

    Wait-ServiceReady -ApiPort $BackendPort -WebPort $FrontendPort

    Write-Host "Backend started in the background (PID $($backendProcess.Id), port $BackendPort)."
    Write-Host "Frontend started in the background (PID $($frontendProcess.Id), port $FrontendPort)."
    Write-Host "Service logs: $logDirectory"
}
catch {
    Stop-StartedProcess -Process $frontendProcess
    Stop-StartedProcess -Process $backendProcess
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    throw
}
