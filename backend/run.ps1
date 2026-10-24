# Starts the StockOS AI backend on a clean port.
#
# The single way to launch the backend in BOTH user mode and agent mode. It
# guarantees the "socket access permission" (WinError 10013) error can never
# happen: any process already listening on the port is stopped first, then
# uvicorn is started. Running two servers on the same port was the root cause.
#
# Usage:
#   powershell -File run.ps1            # default port 8000, hot-reload
#   powershell -File run.ps1 -Port 9000 # different port
#   powershell -File run.ps1 -Reload:$false
param(
    [int]$Port = 8000,
    [switch]$Reload = $true
)

$ErrorActionPreference = "Stop"

# 1) Free the port: WinError 10013 happens when the socket is already bound.
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    $pids = $conns.OwningProcess | Sort-Object -Unique
    foreach ($procId in $pids) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        $name = if ($proc) { $proc.ProcessName } else { "pid $procId" }
        Write-Host "Port $Port is held by $name ($procId) - stopping it to free the port."
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

# 2) Start uvicorn (this script must be run from the backend directory).
$uv = (Get-Command uv -ErrorAction Stop).Source
Write-Host "Starting backend on http://localhost:$Port (reload=$Reload) ..."
if ($Reload) {
    & $uv run uvicorn app.main:app --reload --port $Port
}
else {
    & $uv run uvicorn app.main:app --port $Port
}
