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
    [int]$HealthRetries = 15,
    [int]$HealthIntervalSec = 2,
    [int]$HealthTimeoutSec = 2
)

$ErrorActionPreference = "Stop"

function Get-ContainerId {
    docker ps -a --filter "name=^/$ContainerName$" --format "{{.ID}}"
}

function Is-Running {
    $state = docker inspect -f "{{.State.Running}}" $ContainerName 2>$null
    return $state -eq "true"
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
    docker ps -a --filter "name=^/$ContainerName$" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}"
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
    $url = "http://localhost:$Port/api/isalive"
    for ($i = 1; $i -le $HealthRetries; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $HealthTimeoutSec
            if ($resp.StatusCode -eq 200) {
                Write-Host "GROBID is alive at $url"
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
