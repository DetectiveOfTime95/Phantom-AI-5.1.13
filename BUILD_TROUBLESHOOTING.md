# Windows build troubleshooting (Phantom-AI 5.1.13)

Run `BUILD-PHANTOM-AI.bat` or `build-windows.bat` from the extracted project folder on Windows 10/11 x64. The batch file delegates the checks and build steps to `scripts/build-windows.ps1`; this avoids fragile command parsing in a long `.bat` file.

## Prerequisites

- Node.js 22.13 or newer (64-bit recommended) with npm. Node.js 24.22.2 / npm 11.14.1, as shown in the uploaded build log, satisfy the version requirement.
- Python 3.12 64-bit from python.org, with the Python launcher (`py`) enabled.
- Internet access for npm and pip downloads.

## What changed in 5.1.13

- Replaced the inline `node -e` batch-file version check with a PowerShell version comparison.
- Added a clear stage marker before every external command.
- Logs each command, its output, and its exit code to `build-logs\build-<timestamp>.log`.
- Shows the last 100 log lines automatically if a command fails.
- Verifies Node, npm, Python 3.12 x64, the virtual environment, tests, backend, installer, and portable executable stages separately.
- Recreates `.venv` when its Python version or architecture is incompatible.
- Fixes a Windows PowerShell 5.1 issue where harmless npm/PyInstaller stderr warnings could be treated as terminating errors when `$ErrorActionPreference` was `Stop`. Native stdout and stderr are now streamed to the screen and full log; the actual process exit code determines whether the step failed.

## Outputs

- `release\Phantom-AI Setup 5.1.13.exe`
- `release\Phantom-AI Portable 5.1.13.exe`

The final Windows compilation runs locally on Windows; this package is source code, not a compiled installer.
