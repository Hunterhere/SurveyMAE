param(
    [ValidateSet("start", "stop", "restart", "status", "logs", "rm")]
    [string]$Action = "start",
    [string]$Image = "grobid/grobid:0.9.0-crf", #"grobid/grobid:0.9.0-full" on linux gpu
    [string]$ContainerName = "grobid",
    [int]$Port = 8070,
    [string]$Memory = "2g",
    [string]$LogMaxSize = "10m",
    [int]$LogMaxFile = 5,
    [int]$LogsTail = 200,
    [int]$HealthRetries = 60,
    [int]$HealthIntervalSec = 2,
    [int]$HealthTimeoutSec = 5
)

$ErrorActionPreference = "Stop"

function Get-ContainerId {
    docker ps -a --filter "name=^/$ContainerName$" --format "{{.ID}}"
}

function Is-Running {
    $state = docker inspect -f "{{.State.Running}}" $ContainerName 2>$null
    return $state -eq "true"
}

function Get-MappedHostPort {
    if (-not (Get-ContainerId)) {
        return $null
    }
    $portLine = docker port $ContainerName 8070/tcp 2>$null | Select-Object -First 1
    if ($LASTEXITCODE -ne 0 -or -not $portLine) {
        return $null
    }
    if ($portLine -match ":(\d+)$") {
        return [int]$Matches[1]
    }
    return $null
}

function Ensure-Image {
    docker image inspect $Image 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Image not found. Pulling $Image ..."
        docker pull $Image
    }
}

function Start-Container {
    Ensure-Image

    $containerId = Get-ContainerId
    if ($containerId) {
        docker update --memory $Memory --memory-swap $Memory $ContainerName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to update container '$ContainerName' memory limits."
        }
        if (Is-Running) {
            Write-Host "Container '$ContainerName' is already running."
            return
        }
        Write-Host "Starting existing container '$ContainerName' ..."
        docker start $ContainerName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to start existing container '$ContainerName'."
        }
        return
    }

    Write-Host "Creating and starting container '$ContainerName' ..."
    docker run -d --name $ContainerName --restart unless-stopped --init --ulimit core=0 `
        -p "$Port`:8070" `
        --memory $Memory --memory-swap $Memory `
        --log-opt "max-size=$LogMaxSize" --log-opt "max-file=$LogMaxFile" `
        $Image | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create container '$ContainerName'. Check whether port $Port is already occupied."
    }
}

function Stop-Container {
    if (-not (Get-ContainerId)) {
        Write-Host "Container '$ContainerName' does not exist."
        return
    }
    docker stop $ContainerName | Out-Null
}

function Restart-Container {
    if (-not (Get-ContainerId)) {
        Start-Container
        return
    }
    docker restart $ContainerName | Out-Null
}

function Status-Container {
    $rows = docker ps -a --filter "name=^/$ContainerName$" --format "{{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}"
    if (-not $rows) {
        Write-Host "Container '$ContainerName' not found."
        return
    }
    Write-Host "NAMES`tSTATUS`tPORTS`tIMAGE"
    $rows
}

function Logs-Container {
    if (-not (Get-ContainerId)) {
        Write-Host "Container '$ContainerName' does not exist."
        return
    }
    docker logs --tail $LogsTail -f $ContainerName
}

function Remove-Container {
    if (-not (Get-ContainerId)) {
        Write-Host "Container '$ContainerName' does not exist."
        return
    }
    docker rm -f $ContainerName | Out-Null
}

function Health-Check {
    $startTs = Get-Date
    $mappedPort = Get-MappedHostPort
    $healthPort = if ($mappedPort) { $mappedPort } else { $Port }
    if ($mappedPort -and $mappedPort -ne $Port) {
        Write-Host "Container maps 8070/tcp to host port $mappedPort (requested -Port=$Port). Health check will use $mappedPort."
    }
    if (-not $mappedPort) {
        Write-Host "No host port mapping found for container 8070/tcp. Health check will try -Port=$Port."
    }
    $url = "http://localhost:$healthPort/api/isalive"
    for ($i = 1; $i -le $HealthRetries; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $HealthTimeoutSec
            if ($resp.StatusCode -eq 200) {
                $elapsed = [int]((Get-Date) - $startTs).TotalSeconds
                Write-Host "GROBID is alive at $url (ready in ${elapsed}s)"
                return $true
            }
        } catch {
            # Retry until max attempts reached.
        }
        if ($i -lt $HealthRetries) {
            Start-Sleep -Seconds $HealthIntervalSec
        }
    }

    Write-Host "GROBID health check failed at $url after $HealthRetries attempts."
    Write-Host "Container status:"
    Status-Container
    Write-Host "Recent container logs:"
    docker logs --tail $LogsTail $ContainerName
    return $false
}

switch ($Action) {
    "start" {
        Start-Container
        if (-not (Health-Check)) {
            throw "GROBID did not become healthy."
        }
    }
    "stop" { Stop-Container }
    "restart" {
        Restart-Container
        if (-not (Health-Check)) {
            throw "GROBID did not become healthy after restart."
        }
    }
    "status" { Status-Container }
    "logs" { Logs-Container }
    "rm" { Remove-Container }
}
