[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "restart", "status", "setup")]
    [string]$Action = "start"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = $PSScriptRoot
$ApiRoot = Join-Path $RepoRoot "apps\api"
$WebRoot = Join-Path $RepoRoot "apps\web"
$RuntimeRoot = Join-Path $RepoRoot ".local\runtime"
$ApiPidFile = Join-Path $RuntimeRoot "api.pid"
$WebPidFile = Join-Path $RuntimeRoot "web.pid"
$ApiStdoutLog = Join-Path $RuntimeRoot "api.stdout.log"
$ApiStderrLog = Join-Path $RuntimeRoot "api.stderr.log"
$WebStdoutLog = Join-Path $RuntimeRoot "web.stdout.log"
$WebStderrLog = Join-Path $RuntimeRoot "web.stderr.log"
$ApiHealthUrl = "http://localhost:8000/health/ready"
$WebHealthUrl = "http://localhost:3000/api/health"
$ApiCommandFragment = Join-Path $ApiRoot ".venv\Scripts\python.exe"
$WebCommandFragment = Join-Path $WebRoot "node_modules\next\dist\bin\next"

function Write-Step {
    param([string]$Message)
    Write-Host "[AI Career Agent] $Message" -ForegroundColor Cyan
}

function Write-Utf8File {
    param(
        [string]$Path,
        [string]$Content
    )
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8WithoutBom)
}

function Ensure-LocalConfiguration {
    New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

    $apiEnvironment = Join-Path $ApiRoot ".env"
    if (-not (Test-Path -LiteralPath $apiEnvironment)) {
        Write-Utf8File -Path $apiEnvironment -Content @'
ENVIRONMENT=development
DEV_AUTH_BYPASS=true
DATABASE_URL=sqlite+aiosqlite:///./career_agent.db
AUTO_CREATE_SCHEMA=true
CORS_ORIGINS=http://localhost:3000
CLERK_AUTHORIZED_PARTIES=http://localhost:3000
AI_PROVIDER=deterministic
OPENAI_API_KEY=
MISTRAL_API_KEY=
AI_MODEL=gpt-5.6-sol
AI_SAFETY_SALT=
MAX_IMPORT_BYTES=10000000
'@
        Write-Step "Created apps/api/.env with safe local SQLite settings."
    }

    $webEnvironment = Join-Path $WebRoot ".env.local"
    if (-not (Test-Path -LiteralPath $webEnvironment)) {
        Write-Utf8File -Path $webEnvironment -Content @'
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=
NEXT_PUBLIC_DEV_AUTH_BYPASS=true
'@
        Write-Step "Created apps/web/.env.local for the local API."
    }
}

function Get-CommandPath {
    param([string[]]$Names)
    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) { return $command.Source }
    }
    return $null
}

function Ensure-LocalDependencies {
    $nodeCommand = Get-CommandPath -Names @("node.exe", "node")
    $npmCommand = Get-CommandPath -Names @("npm.cmd", "npm")
    if (-not $nodeCommand -or -not $npmCommand) {
        throw "Node.js 22 and npm are required. Install them, then run .\dev.cmd again."
    }

    $nodeMajor = [int]((& $nodeCommand --version).TrimStart("v").Split(".")[0])
    if ($nodeMajor -lt 22) {
        throw "Node.js 22 or newer is required; found $(& $nodeCommand --version)."
    }

    $pythonCommand = Join-Path $ApiRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $pythonCommand)) {
        $pythonLauncher = Get-CommandPath -Names @("py.exe", "py")
        if ($pythonLauncher) {
            Write-Step "Creating the Python 3.12 virtual environment..."
            & $pythonLauncher -3.12 -m venv (Join-Path $ApiRoot ".venv")
        } else {
            $systemPython = Get-CommandPath -Names @("python.exe", "python")
            if (-not $systemPython) {
                throw "Python 3.12 is required. Install it, then run .\dev.cmd again."
            }
            Write-Step "Creating the Python virtual environment..."
            & $systemPython -m venv (Join-Path $ApiRoot ".venv")
        }
        if ($LASTEXITCODE -ne 0) { throw "Could not create the Python virtual environment." }
    }

    $pythonVersion = (& $pythonCommand -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ([version]$pythonVersion -lt [version]"3.12") {
        throw "Python 3.12 or newer is required; found $pythonVersion."
    }

    Push-Location $ApiRoot
    try {
        & $pythonCommand -c "import career_agent_api, openai, uvicorn" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Step "Installing API dependencies..."
            & $pythonCommand -m pip install -e ".[dev]"
            if ($LASTEXITCODE -ne 0) { throw "Could not install API dependencies." }
        }
    } finally {
        Pop-Location
    }

    $nextCommand = Join-Path $WebRoot "node_modules\next\dist\bin\next"
    if (-not (Test-Path -LiteralPath $nextCommand)) {
        Write-Step "Installing web dependencies..."
        Push-Location $WebRoot
        try {
            & $npmCommand ci
            if ($LASTEXITCODE -ne 0) { throw "Could not install web dependencies." }
        } finally {
            Pop-Location
        }
    }

    return @{
        Node = $nodeCommand
        Python = $pythonCommand
        Next = $nextCommand
    }
}

function Get-RecordedProcessIdentifier {
    param(
        [string]$PidFile,
        [string]$ExpectedCommandFragment
    )
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }

    $rawIdentifier = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    $processIdentifier = 0
    if (-not [int]::TryParse($rawIdentifier, [ref]$processIdentifier)) {
        Remove-Item -LiteralPath $PidFile -Force
        return $null
    }

    if (-not (Get-Process -Id $processIdentifier -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $PidFile -Force
        return $null
    }

    $runtimeProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $processIdentifier" -ErrorAction SilentlyContinue
    if (
        -not $runtimeProcess -or
        -not $runtimeProcess.CommandLine -or
        $runtimeProcess.CommandLine.IndexOf($ExpectedCommandFragment, [System.StringComparison]::OrdinalIgnoreCase) -lt 0
    ) {
        Remove-Item -LiteralPath $PidFile -Force
        return $null
    }
    return $processIdentifier
}

function Get-PortOwner {
    param([int]$Port)
    $connection = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($connection) { return [int]$connection.OwningProcess }
    return $null
}

function Test-Endpoint {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
    } catch {
        return $false
    }
}

function Wait-ForEndpoint {
    param(
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSeconds = 60
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-Endpoint -Url $Url) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name did not become healthy within $TimeoutSeconds seconds."
}

function Stop-ProcessTree {
    param([int]$ProcessIdentifier)
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessIdentifier" -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessIdentifier ([int]$child.ProcessId)
    }
    Stop-Process -Id $ProcessIdentifier -Force -ErrorAction SilentlyContinue
}

function Stop-ManagedService {
    param(
        [string]$Name,
        [string]$PidFile,
        [string]$ExpectedCommandFragment
    )
    $processIdentifier = Get-RecordedProcessIdentifier -PidFile $PidFile -ExpectedCommandFragment $ExpectedCommandFragment
    if (-not $processIdentifier) {
        Write-Step "$Name is not managed by this launcher."
        return
    }

    Write-Step "Stopping $Name (PID $processIdentifier)..."
    Stop-ProcessTree -ProcessIdentifier $processIdentifier
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

function Show-Status {
    $apiProcessIdentifier = Get-RecordedProcessIdentifier -PidFile $ApiPidFile -ExpectedCommandFragment $ApiCommandFragment
    $webProcessIdentifier = Get-RecordedProcessIdentifier -PidFile $WebPidFile -ExpectedCommandFragment $WebCommandFragment
    $apiOwner = Get-PortOwner -Port 8000
    $webOwner = Get-PortOwner -Port 3000

    $apiState = if (Test-Endpoint -Url $ApiHealthUrl) { "healthy" } elseif ($apiOwner) { "unhealthy" } else { "stopped" }
    $webState = if (Test-Endpoint -Url $WebHealthUrl) { "healthy" } elseif ($webOwner) { "unhealthy" } else { "stopped" }

    Write-Host "API : $apiState | managed PID: $apiProcessIdentifier | listener PID: $apiOwner | http://localhost:8000/docs"
    Write-Host "Web : $webState | managed PID: $webProcessIdentifier | listener PID: $webOwner | http://localhost:3000"
    Write-Host "Logs: $RuntimeRoot"
}

function Start-LocalStack {
    Ensure-LocalConfiguration
    $commands = Ensure-LocalDependencies
    $startedApi = $false
    $startedWeb = $false

    try {
        $apiProcessIdentifier = Get-RecordedProcessIdentifier -PidFile $ApiPidFile -ExpectedCommandFragment $ApiCommandFragment
        if ($apiProcessIdentifier -and (Test-Endpoint -Url $ApiHealthUrl)) {
            Write-Step "API is already healthy (PID $apiProcessIdentifier)."
        } else {
            $apiOwner = Get-PortOwner -Port 8000
            if ($apiOwner) {
                throw "Port 8000 is already used by PID $apiOwner and is not managed by this launcher."
            }
            Write-Step "Starting API on http://localhost:8000..."
            $apiProcess = Start-Process `
                -FilePath $commands.Python `
                -ArgumentList @("-m", "uvicorn", "career_agent_api.main:app", "--app-dir", "src", "--host", "127.0.0.1", "--port", "8000") `
                -WorkingDirectory $ApiRoot `
                -WindowStyle Hidden `
                -RedirectStandardOutput $ApiStdoutLog `
                -RedirectStandardError $ApiStderrLog `
                -PassThru
            Write-Utf8File -Path $ApiPidFile -Content ([string]$apiProcess.Id)
            $startedApi = $true
            Wait-ForEndpoint -Name "API" -Url $ApiHealthUrl
            $apiListener = Get-PortOwner -Port 8000
            if (-not $apiListener) { throw "API is healthy but no listener was found on port 8000." }
            Write-Utf8File -Path $ApiPidFile -Content ([string]$apiListener)
        }

        $webProcessIdentifier = Get-RecordedProcessIdentifier -PidFile $WebPidFile -ExpectedCommandFragment $WebCommandFragment
        if ($webProcessIdentifier -and (Test-Endpoint -Url $WebHealthUrl)) {
            Write-Step "Web app is already healthy (PID $webProcessIdentifier)."
        } else {
            $webOwner = Get-PortOwner -Port 3000
            if ($webOwner) {
                throw "Port 3000 is already used by PID $webOwner and is not managed by this launcher."
            }
            Write-Step "Starting web app on http://localhost:3000..."
            $quotedNextCommand = '"' + $commands.Next + '"'
            $webProcess = Start-Process `
                -FilePath $commands.Node `
                -ArgumentList @($quotedNextCommand, "dev", "--hostname", "localhost", "--port", "3000") `
                -WorkingDirectory $WebRoot `
                -WindowStyle Hidden `
                -RedirectStandardOutput $WebStdoutLog `
                -RedirectStandardError $WebStderrLog `
                -PassThru
            Write-Utf8File -Path $WebPidFile -Content ([string]$webProcess.Id)
            $startedWeb = $true
            Wait-ForEndpoint -Name "Web app" -Url $WebHealthUrl
            $webListener = Get-PortOwner -Port 3000
            if (-not $webListener) { throw "Web app is healthy but no listener was found on port 3000." }
        }
    } catch {
        if ($startedWeb) {
            $webRecordedProcess = Get-RecordedProcessIdentifier -PidFile $WebPidFile -ExpectedCommandFragment $WebCommandFragment
            if (-not $webRecordedProcess) {
                $webStartedOwner = Get-PortOwner -Port 3000
                if ($webStartedOwner) { Write-Utf8File -Path $WebPidFile -Content ([string]$webStartedOwner) }
            }
            Stop-ManagedService -Name "Web app" -PidFile $WebPidFile -ExpectedCommandFragment $WebCommandFragment
        }
        if ($startedApi) {
            $apiStartedOwner = Get-PortOwner -Port 8000
            if ($apiStartedOwner) { Write-Utf8File -Path $ApiPidFile -Content ([string]$apiStartedOwner) }
            Stop-ManagedService -Name "API" -PidFile $ApiPidFile -ExpectedCommandFragment $ApiCommandFragment
        }
        Write-Host "API log: $ApiStderrLog" -ForegroundColor Yellow
        Write-Host "Web log: $WebStderrLog" -ForegroundColor Yellow
        throw
    }

    Show-Status
    Write-Host "Open http://localhost:3000" -ForegroundColor Green
}

function Stop-LocalStack {
    Stop-ManagedService -Name "Web app" -PidFile $WebPidFile -ExpectedCommandFragment $WebCommandFragment
    Stop-ManagedService -Name "API" -PidFile $ApiPidFile -ExpectedCommandFragment $ApiCommandFragment
    Show-Status
}

switch ($Action) {
    "setup" {
        Ensure-LocalConfiguration
        $null = Ensure-LocalDependencies
        Write-Step "Local setup is ready. Run .\dev.cmd start."
    }
    "start" { Start-LocalStack }
    "stop" { Stop-LocalStack }
    "restart" {
        Stop-LocalStack
        Start-LocalStack
    }
    "status" { Show-Status }
}
