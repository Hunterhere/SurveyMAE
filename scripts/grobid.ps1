param(
    [ValidateSet("start", "stop", "restart", "status", "logs", "rm")]
    [string]$Action = "start",
    [string]$Image = "grobid/grobid:0.8.2-full",
    [string]$ContainerName = "grobid",
    [int]$Port = 8070,
    [string]$LogMaxSize = "10m",
    [int]$LogMaxFile = 5,
    [int]$LogsTail = 200
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
        if (Is-Running) {
            Write-Host "Container '$ContainerName' is already running."
            return
        }
        Write-Host "Starting existing container '$ContainerName' ..."
        docker start $ContainerName | Out-Null
        return
    }

    Write-Host "Creating and starting container '$ContainerName' ..."
    docker run -d --name $ContainerName --restart unless-stopped --init --ulimit core=0 `
        -p "$Port`:8070" `
        --log-opt "max-size=$LogMaxSize" --log-opt "max-file=$LogMaxFile" `
        $Image | Out-Null
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
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) {
            Write-Host "GROBID is alive at $url"
            return
        }
    } catch {
        Write-Host "GROBID health check failed at $url"
    }
}

switch ($Action) {
    "start" {
        Start-Container
        Start-Sleep -Seconds 2
        Health-Check
    }
    "stop" { Stop-Container }
    "restart" {
        Restart-Container
        Start-Sleep -Seconds 2
        Health-Check
    }
    "status" { Status-Container }
    "logs" { Logs-Container }
    "rm" { Remove-Container }
}
