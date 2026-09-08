param(
    [ValidateSet('start', 'restart', 'stop', 'check', 'repair')]
    [string]$Action = 'start',
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
function Assert-Exit([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." }
}
function Get-DependencyHash([string[]]$Paths) {
    return (($Paths | Sort-Object | ForEach-Object {
        if (Test-Path -LiteralPath $_) { (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash }
    }) -join ':')
}
try {
    # Serialize double-clicks, including dependency setup and restart.
    $mutex = New-Object System.Threading.Mutex($false, ('Local\TubeAiFolw-' + ($root -replace '[^a-zA-Z0-9]', '_')))
    $acquired = $false
    try { $acquired = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $acquired = $true }
    if (-not $acquired) { Write-Host 'TubeAiFolw launcher is already working.'; exit 0 }
    if ($Action -in @('stop', 'restart')) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'Stop_TubeAIFlow.ps1')
        Assert-Exit 'Stop'
        if ($Action -eq 'stop') { exit 0 }
    }
    $null = Get-Command npm.cmd -ErrorAction Stop
    if ($Action -eq 'check') {
        if (-not (Test-Path -LiteralPath $python)) { throw 'Backend environment missing. Run the launcher normally to install.' }
        & $python --version
        Assert-Exit 'Python check'
        if (-not (Test-Path -LiteralPath (Join-Path $frontend 'node_modules'))) { throw 'Frontend dependencies missing.' }
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Start_TubeAIFlowServices.ps1') -BackendPort 18080 -Check
        Assert-Exit 'Service launcher check'
        Write-Host '[OK] Check completed without installing dependencies or starting services.'
        exit 0
    }
    if (-not (Test-Path -LiteralPath $python)) {
        if (Get-Command py.exe -ErrorAction SilentlyContinue) {
            & py.exe -3.12 -m venv (Join-Path $backend '.venv')
        } else {
            & python.exe -m venv (Join-Path $backend '.venv')
        }
        Assert-Exit 'Create Python environment'
    }
    & $python --version
    Assert-Exit 'Python environment'
    $requirements = @(Get-ChildItem -LiteralPath $backend -Filter 'requirements*.txt' | ForEach-Object FullName)
    $backendHash = Get-DependencyHash ($requirements + (Join-Path $backend '.venv\pyvenv.cfg'))
    $backendStamp = Join-Path $backend '.venv\tubeaifolw-dependencies.hash'
    if ($Action -eq 'repair' -or -not (Test-Path -LiteralPath $backendStamp) -or (Get-Content -Raw -LiteralPath $backendStamp).Trim() -ne $backendHash) {
        Push-Location $backend
        try { & $python -m pip install -r requirements.txt; Assert-Exit 'Backend dependency installation' } finally { Pop-Location }
        Set-Content -LiteralPath $backendStamp -Value $backendHash -Encoding ASCII
    }
    $frontendStamp = Join-Path $frontend 'node_modules\.tubeaifolw-dependencies.hash'
    $frontendFiles = @((Join-Path $frontend 'package.json'), (Join-Path $frontend 'package-lock.json'))
    $frontendHash = Get-DependencyHash $frontendFiles
    if ($Action -eq 'repair' -or -not (Test-Path -LiteralPath $frontendStamp) -or (Get-Content -Raw -LiteralPath $frontendStamp).Trim() -ne $frontendHash) {
        Push-Location $frontend
        try { & npm.cmd install; Assert-Exit 'Frontend dependency installation' } finally { Pop-Location }
        Set-Content -LiteralPath $frontendStamp -Value (Get-DependencyHash $frontendFiles) -Encoding ASCII
    }
    Push-Location $backend
    try { $port = & $python -m app.find_available_port; Assert-Exit 'Port selection' } finally { Pop-Location }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Start_TubeAIFlowServices.ps1') -BackendPort ([int]$port)
    Assert-Exit 'Service startup'
    if (-not $NoBrowser) {
        try { Start-Process 'http://127.0.0.1:5173' }
        catch { Write-Host 'TubeAiFolw is ready. Open http://127.0.0.1:5173 in your browser.' }
    }
} catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($acquired) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}

