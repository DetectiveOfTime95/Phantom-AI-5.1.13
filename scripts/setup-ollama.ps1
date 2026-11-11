param(
  [string]$Model = "qwen3:4b"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step([string]$Message) {
  Write-Output "PHANTOM_SETUP: $Message"
}

function Get-OllamaExe {
  $command = Get-Command ollama.exe -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
    (Join-Path $env:LOCALAPPDATA "Ollama\ollama.exe"),
    (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
  )
  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path $candidate)) { return $candidate }
  }
  return $null
}

function Test-OllamaApi {
  try {
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2
    return $true
  } catch { return $false }
}

$ollama = Get-OllamaExe
if (-not $ollama) {
  Write-Step "Downloading the official Ollama for Windows installer..."
  $installer = Join-Path $env:TEMP "Phantom-OllamaSetup.exe"
  Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $installer

  Write-Step "Verifying the Ollama installer signature..."
  $signature = Get-AuthenticodeSignature -FilePath $installer
  if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notmatch "Ollama") {
    Remove-Item $installer -Force -ErrorAction SilentlyContinue
    throw "The downloaded Ollama installer did not pass Authenticode signature verification."
  }

  Write-Step "Installing Ollama for the current Windows user..."
  $process = Start-Process -FilePath $installer -ArgumentList @("/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES") -Wait -PassThru
  if ($process.ExitCode -ne 0) { throw "Ollama installer exited with code $($process.ExitCode)." }
  Remove-Item $installer -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 3
  $ollama = Get-OllamaExe
  if (-not $ollama) { throw "Ollama installed but ollama.exe could not be found." }
}

if (-not (Test-OllamaApi)) {
  Write-Step "Starting the local Ollama service..."
  Start-Process -FilePath $ollama -ArgumentList @("serve") -WindowStyle Hidden
  $ready = $false
  for ($i = 0; $i -lt 60; $i++) {
    if (Test-OllamaApi) { $ready = $true; break }
    Start-Sleep -Seconds 1
  }
  if (-not $ready) { throw "Ollama did not start its local API at 127.0.0.1:11434." }
}

Write-Step "Checking local model $Model..."
$tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 10
$names = @($tags.models | ForEach-Object { $_.name })
if (-not ($names -contains $Model)) {
  Write-Step "Downloading local AI model $Model. This can take several gigabytes of storage and time..."
  & $ollama pull $Model
  if ($LASTEXITCODE -ne 0) { throw "Ollama could not download model $Model (exit $LASTEXITCODE)." }
}
Write-Step "Ollama is ready. Model: $Model. Inference will use the local machine."
exit 0
