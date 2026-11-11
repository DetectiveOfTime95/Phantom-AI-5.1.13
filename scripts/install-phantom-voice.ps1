$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Write-Host "Installing Microsoft Edge TTS for Phantom-AI..." -ForegroundColor Cyan

$Python = $env:PHANTOM_PYTHON
if (-not $Python -or -not (Test-Path $Python)) {
    $Candidates = @(
        (Join-Path $Root ".venv\Scripts\python.exe"),
        (Join-Path $HOME "Miniconda3\python.exe"),
        (Join-Path $HOME "Anaconda3\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
    )
    $Python = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Python) {
    $Command = Get-Command python -ErrorAction SilentlyContinue
    if ($Command) { $Python = $Command.Source }
}
if (-not $Python) { throw "Python was not found. Install Python 3.12 or set PHANTOM_PYTHON." }

Write-Host "Using Python: $Python" -ForegroundColor DarkCyan
& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not update pip." }
& $Python -m pip install -r (Join-Path $Root "requirements-voice.txt")
if ($LASTEXITCODE -ne 0) { throw "Edge TTS installation failed." }
& $Python -c "import edge_tts; print('Edge TTS import: OK')"
if ($LASTEXITCODE -ne 0) { throw "Edge TTS verification failed." }
Write-Host "Edge TTS is installed. Speech synthesis requires internet access when Phantom speaks." -ForegroundColor Green
