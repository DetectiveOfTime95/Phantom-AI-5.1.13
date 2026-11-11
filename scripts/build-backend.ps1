$ErrorActionPreference = "Stop"

function Invoke-BackendNative {
  param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter(Mandatory = $false)][string[]]$Arguments = @(),
    [Parameter(Mandatory = $true)][string]$Description
  )
  Write-Host "========== $Description =========="
  Write-Host (">>> " + $FilePath + " " + ($Arguments -join " "))
  $previousPreference = $ErrorActionPreference
  $exitCode = 0
  try {
    $ErrorActionPreference = "Continue"
    & $FilePath @Arguments 2>&1 | ForEach-Object {
      if ($_ -is [System.Management.Automation.ErrorRecord]) { $line = $_.ToString() }
      else { $line = [string]$_ }
      Write-Host $line
    }
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) { $exitCode = 0 }
  } catch {
    $exitCode = 1
    Write-Host "Command invocation error: $($_.Exception.Message)"
  } finally {
    $ErrorActionPreference = $previousPreference
  }

  Write-Host "Exit code: $exitCode"
  if ($exitCode -ne 0) { throw "$Description failed with exit code $exitCode." }
  return $output
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$python = $venvPython

if (-not (Test-Path -LiteralPath $python)) {
  throw "The project Python environment is missing. Run build-windows.bat to create .venv first."
}

Push-Location $projectRoot
try {
  $pythonInfo = Invoke-BackendNative -FilePath $python -Arguments @('-c', "import sys,struct; print(sys.version); print(str(struct.calcsize('P')*8)+'-bit'); assert sys.version_info[:2] == (3,12); assert struct.calcsize('P') == 8") -Description 'Validate backend Python'
  Write-Host "Using backend build Python: $($pythonInfo -join ', ')"

  Invoke-BackendNative -FilePath $python -Arguments @('-m', 'PyInstaller', '--version') -Description 'Check PyInstaller version' | Out-Null

  $backendOutput = Join-Path $projectRoot "bk"
  $workOutput = Join-Path $projectRoot ".pyinstaller-work"
  if (Test-Path -LiteralPath $backendOutput) {
    Remove-Item -LiteralPath $backendOutput -Recurse -Force
  }
  if (Test-Path -LiteralPath $workOutput) {
    Remove-Item -LiteralPath $workOutput -Recurse -Force
  }

  Invoke-BackendNative -FilePath $python -Arguments @('-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', $projectRoot, '--workpath', $workOutput, (Join-Path $projectRoot 'backend.spec')) -Description 'Package Phantom-AI Python backend' | Out-Null

  $expectedExe = Join-Path $backendOutput "phantom-backend.exe"
  if (-not (Test-Path -LiteralPath $expectedExe)) {
    $alternateExe = Join-Path $projectRoot "dist\bk\phantom-backend.exe"
    if (Test-Path -LiteralPath $alternateExe) {
      New-Item -ItemType Directory -Force -Path $backendOutput | Out-Null
      Copy-Item -LiteralPath $alternateExe -Destination $expectedExe -Force
    }
  }
  if (-not (Test-Path -LiteralPath $expectedExe)) {
    $found = Get-ChildItem -LiteralPath $projectRoot -Filter "phantom-backend.exe" -Recurse -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
    throw "PyInstaller completed but phantom-backend.exe was not found at bk\phantom-backend.exe. Found: $($found -join '; ')"
  }
  Write-Host "Backend executable created: $expectedExe"
}
finally {
  Pop-Location
}
