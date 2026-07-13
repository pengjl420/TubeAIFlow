param(
    [int[]]$Ports = @(18080, 5173)
)

$ErrorActionPreference = "SilentlyContinue"

function Get-ProcessMap {
    $map = @{}
    foreach ($process in Get-CimInstance Win32_Process) {
        $map[[int]$process.ProcessId] = $process
    }
    return $map
}

function Get-ListenerProcessIds {
    $ids = @()
    foreach ($line in & netstat.exe -ano -p tcp) {
        if ($line -match "^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$") {
            $port = [int]$Matches[1]
            if ($Ports -contains $port) {
                $ids += [int]$Matches[2]
            }
        }
    }
    return @($ids | Select-Object -Unique)
}

function Get-AppProcessRoot([int]$ProcessId, $ProcessMap) {
    $target = $ProcessId
    $current = $ProcessId

    for ($depth = 0; $depth -lt 8 -and $current -gt 0; $depth++) {
        $process = $ProcessMap[$current]
        if (-not $process) {
            break
        }

        $commandLine = [string]$process.CommandLine
        if ($commandLine -match "app\.run|uvicorn|vite|npm(\.cmd)?\s+run\s+dev") {
            # Select the highest matching launcher/reloader so its children
            # cannot recreate the listener after only the server is killed.
            $target = [int]$process.ProcessId
        }
        $current = [int]$process.ParentProcessId
    }
    return $target
}

for ($attempt = 1; $attempt -le 5; $attempt++) {
    $listeners = @(Get-ListenerProcessIds)
    if ($listeners.Count -eq 0) {
        break
    }

    $processMap = Get-ProcessMap
    foreach ($listener in $listeners) {
        $target = Get-AppProcessRoot -ProcessId ([int]$listener) -ProcessMap $processMap
        Write-Host "Stopping process tree $target for listener $listener..."
        & taskkill.exe /PID $target /T /F | Out-Null
    }
    Start-Sleep -Milliseconds 400
}

$remaining = @(Get-ListenerProcessIds)
if ($remaining.Count -gt 0) {
    foreach ($processId in $remaining) {
        Write-Host "[WARN] Listener $processId cannot be stopped; the launcher will select a fallback backend port."
    }
}
