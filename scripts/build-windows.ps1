# Phantom-AI Windows builder. Run through build-windows.bat.
# Designed for Windows PowerShell 5.1 and Windows 10/11 x64.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

$logDirectory = Join-Path $projectRoot 'build-logs'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$script:LogFile = Join-Path $logDirectory "build-$stamp.log"
"Phantom-AI 5.1.13 Windows build log" | Set-Content -LiteralPath $script:LogFile -Encoding UTF8
"Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')" | Add-Content -LiteralPath $script:LogFile -Encoding UTF8

function Write-LogLine {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Message)
    Write-Host $Message
    Add-Content -LiteralPath $script:LogFile -Value $Message -Encoding UTF8
}

function Invoke-LoggedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $false)][string[]]$Arguments = @(),
        [Parameter(Mandatory = $true)][string]$Description
    )

    Write-LogLine ""
    Write-LogLine "========== $Description =========="
    Write-LogLine (">>> " + $FilePath + ' ' + ($Arguments -join ' '))

    # Windows PowerShell 5.1 can promote native stderr (including harmless npm
    # deprecation warnings) into NativeCommandError records. With the script-wide
    # ErrorActionPreference=Stop this can abort npm before it finishes. Temporarily
    # use Continue while the process runs, stream BOTH output channels to the console
    # and log, then trust only the native process exit code.
    $previousErrorActionPreference = $ErrorActionPreference
    $nativeExitCode = 0
    try {
        $ErrorActionPreference = 'Continue'
        & $FilePath @Arguments 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                $line = $_.ToString()
            } else {
                $line = [string]$_
            }
            Write-Host $line
            Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8
        }
        $nativeExitCode = $LASTEXITCODE
        if ($null -eq $nativeExitCode) { $nativeExitCode = 0 }
    }
    catch {
        $nativeExitCode = 1
        $errorLine = "Command invocation error: $($_.Exception.Message)"
        Write-Host $errorLine
        Add-Content -LiteralPath $script:LogFile -Value $errorLine -Encoding UTF8
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    Write-LogLine "Exit code: $nativeExitCode"
    if ($nativeExitCode -ne 0) {
        throw "$Description failed with exit code $nativeExitCode. See $script:LogFile"
    }
}

try {
    Write-LogLine ''
    Write-LogLine '================================================='
    Write-LogLine '       PHANTOM-AI 5.1.13 WINDOWS BUILDER'
    Write-LogLine '================================================='
    Write-LogLine "Project: $projectRoot"
    Write-LogLine "Log: $script:LogFile"

    Write-LogLine '[CHECK 1/5] Locating Node.js, npm, and Python launcher...'
    $nodeCommand = Get-Command 'node.exe' -ErrorAction Stop
    $npmCommand = Get-Command 'npm.cmd' -ErrorAction Stop
    $pythonLauncher = Get-Command 'py.exe' -ErrorAction Stop
    $nodeExe = $nodeCommand.Source
    $npmCmd = $npmCommand.Source
    $pyExe = $pythonLauncher.Source

    Invoke-LoggedCommand -FilePath $nodeExe -Arguments @('--version') -Description 'Node.js version'
    Invoke-LoggedCommand -FilePath $npmCmd -Arguments @('--version') -Description 'npm version'

    # Parse the Node version in PowerShell rather than embedding comparison operators
    # and nested parentheses in a cmd.exe `node -e` expression.
    $nodeVersionText = (& $nodeExe --version 2>&1 | Select-Object -First 1).ToString().Trim()
    $nodeExit = $LASTEXITCODE
    if ($nodeExit -ne 0) { throw "Node.js version query failed with exit code $nodeExit." }
    $nodeVersion = [version]($nodeVersionText.TrimStart('v'))
    Write-LogLine "Detected Node.js version: $nodeVersion"
    if ($nodeVersion -lt [version]'22.13.0') {
        throw "Node.js 22.13.0 or newer is required. Detected $nodeVersionText."
    }

    Write-LogLine '[CHECK 2/5] Verifying Python 3.12 x64...'
    $pythonCheck = "import sys,struct; print('Build Python:',sys.version); print('Architecture:',struct.calcsize('P')*8,'bit'); assert sys.version_info[:2] == (3,12), 'Python 3.12 is required'; assert struct.calcsize('P') == 8, '64-bit Python is required'"
    Invoke-LoggedCommand -FilePath $pyExe -Arguments @('-3.12', '-c', $pythonCheck) -Description 'Python 3.12 x64 check'

    $venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    $venvIsValid = $false
    if (Test-Path -LiteralPath $venvPython) {
        Write-LogLine '[CHECK 3/5] Checking existing .venv Python version and architecture...'
        $venvCheck = "import sys,struct; print('Existing venv:',sys.version); print('Architecture:',struct.calcsize('P')*8,'bit'); assert sys.version_info[:2] == (3,12); assert struct.calcsize('P') == 8"
        $venvOutput = & $venvPython -c $venvCheck 2>&1
        $venvExitCode = $LASTEXITCODE
        foreach ($line in $venvOutput) { Write-LogLine ([string]$line) }
        if ($venvExitCode -eq 0) {
            $venvIsValid = $true
            Write-LogLine 'Existing .venv is compatible.'
        } else {
            Write-LogLine 'Existing .venv is incompatible or damaged; removing it and recreating it.'
            Remove-Item -LiteralPath (Join-Path $projectRoot '.venv') -Recurse -Force
        }
    }

    if (-not $venvIsValid) {
        Invoke-LoggedCommand -FilePath $pyExe -Arguments @('-3.12', '-m', 'venv', '.venv') -Description 'Create clean Python 3.12 x64 virtual environment'
    }

    if (-not (Test-Path -LiteralPath $venvPython)) {
        throw "Virtual environment creation completed but python.exe was not found: $venvPython"
    }

    Write-LogLine '[CHECK 4/5] Installing Python and Node dependencies...'
    Invoke-LoggedCommand -FilePath $venvPython -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel') -Description 'Upgrade Python packaging tools'
    Invoke-LoggedCommand -FilePath $venvPython -Arguments @('-m', 'pip', 'install', '--prefer-binary', '-r', 'requirements.txt') -Description 'Install Phantom-AI Python dependencies'

    if (Test-Path -LiteralPath (Join-Path $projectRoot 'package-lock.json')) {
        Invoke-LoggedCommand -FilePath $npmCmd -Arguments @('ci', '--no-audit', '--no-fund', '--loglevel=verbose') -Description 'Install locked Electron dependencies (npm ci)'
    } else {
        Invoke-LoggedCommand -FilePath $npmCmd -Arguments @('install', '--no-audit', '--no-fund', '--loglevel=verbose') -Description 'Install Electron dependencies (npm install)'
    }

    Write-LogLine '[CHECK 5/5] Running tests and packaging Windows executables...'
    Invoke-LoggedCommand -FilePath $npmCmd -Arguments @('run', 'test:all') -Description 'Wake-word, voice, and network-security tests'
    Invoke-LoggedCommand -FilePath $npmCmd -Arguments @('run', 'dist') -Description 'Build Python backend and Electron Windows installers'

    $releaseDirectory = Join-Path $projectRoot 'release'
    $setupExe = Join-Path $releaseDirectory 'Phantom-AI Setup 5.1.13.exe'
    $portableExe = Join-Path $releaseDirectory 'Phantom-AI Portable 5.1.13.exe'
    if (-not (Test-Path -LiteralPath $setupExe)) {
        throw "electron-builder exited successfully, but the installer was not found: $setupExe"
    }
    if (-not (Test-Path -LiteralPath $portableExe)) {
        throw "electron-builder exited successfully, but the portable executable was not found: $portableExe"
    }

    Write-LogLine ''
    Write-LogLine 'BUILD SUCCEEDED.'
    Write-LogLine "Installer: $setupExe"
    Write-LogLine "Portable: $portableExe"
    Write-LogLine "Finished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')"
    Write-Host ''
    Write-Host 'SUCCESS. Both Windows executables are in the release folder.' -ForegroundColor Green
    Write-Host "Build log: $script:LogFile"
    exit 0
}
catch {
    $failureMessage = $_.Exception.Message
    Write-LogLine '[ERROR HANDLER] Capturing build failure.'
    Write-LogLine 'BUILD FAILED.'
    Write-LogLine $failureMessage
    Write-LogLine "Stopped: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')"
    Write-Host ''
    Write-Host 'BUILD FAILED. The exact error and preceding command are shown above.' -ForegroundColor Red
    Write-Host 'Full log:'
    Write-Host $script:LogFile
    Write-Host ''
    if (Test-Path -LiteralPath $script:LogFile) {
        Get-Content -LiteralPath $script:LogFile -Tail 100 | Write-Host
    }
    exit 1
}
