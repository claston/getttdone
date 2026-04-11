[CmdletBinding()]
param(
    [string]$Ports = "8000,3000",
    [switch]$ListOnly
)

$ErrorActionPreference = "Stop"

$portValues = @()
foreach ($token in ($Ports -split "[,\s]+" | Where-Object { $_ -ne "" })) {
    if ($token -match "^\d+$") {
        $portValues += [int]$token
    }
}
$portValues = $portValues | Sort-Object -Unique
if (-not $portValues -or $portValues.Count -eq 0) {
    throw "No valid ports provided. Example: -Ports '8000,3000'"
}

function Get-PidsByPort {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $lines = netstat -ano | Select-String -Pattern "[:\.]$Port\s+"
    $pids = @()

    foreach ($line in $lines) {
        $parts = ($line.Line.Trim() -split "\s+") | Where-Object { $_ -ne "" }
        if ($parts.Length -lt 4) {
            continue
        }

        $localEndpoint = $parts[1]
        if ($localEndpoint -notmatch "[:\.]$Port$") {
            continue
        }

        $pidValue = $parts[-1]
        if ($pidValue -match "^\d+$" -and [int]$pidValue -gt 0) {
            $pids += [int]$pidValue
        }
    }

    return $pids | Sort-Object -Unique
}

foreach ($port in $portValues) {
    $pids = Get-PidsByPort -Port $port
    if (-not $pids -or $pids.Count -eq 0) {
        Write-Host "No process listening on port $port."
        continue
    }

    Write-Host "Port $port -> PIDs: $($pids -join ', ')"
    if ($ListOnly) {
        continue
    }

    foreach ($processId in $pids) {
        try {
            # Kill process tree because dev servers (e.g., uvicorn --reload) can respawn workers.
            $output = & taskkill /PID $processId /T /F 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "Stopped PID $processId (tree) on port $port."
            }
            else {
                $joined = ($output | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ -ne "" }) -join " | "
                Write-Warning "Could not stop PID $processId on port ${port}. taskkill exit=$LASTEXITCODE. $joined"
            }
        }
        catch {
            Write-Warning "Could not stop PID $processId on port ${port}: $($_.Exception.Message)"
        }
    }
}
