# Phantom-AI 5.1.13 setup (Windows)

## Requirements

- Windows 10 or 11, 64-bit.
- Node.js 22.13 or newer (includes npm).
- Python 3.12, 64-bit, with the Python launcher enabled.
- Internet access for first-time dependency installation, the initial Ollama/model download, and the one-time Vosk speech-model download.
- A microphone if you want voice wake-word support.

## Build the desktop app

No GitHub setup or cloud build is used. Everything is compiled locally on your Windows PC.

1. Extract the Phantom-AI project ZIP.
2. Double-click `build-windows.bat` in the extracted project folder.
3. The script creates `.venv`, installs Python and Node dependencies, builds the Python backend, and runs Electron Builder.
4. Find the Windows installer and portable EXE in `release/`.

No payment server, user account, activation code, license file, or license-generation tool is required.

## First run

1. Open Phantom-AI.
2. Accept the Ollama setup prompt if Ollama or the configured model is missing.
3. Turn **VOICE: ON** and allow microphone permission to use “Hey Phantom”. The first activation downloads the small English Vosk model (about 40 MB); after that speech recognition works locally without a speech-recognition network service. Edge TTS voice output still requires internet. Voice listening is optional; typed commands work without it.
4. Connect Home Assistant from **Console → HOME** to enable supported smart-home controls.

The optional Stripe Payment Links under **SUPPORT** are voluntary support only. They do not gate or unlock any application feature.


### Enable live Internet features

Open Console → ONLINE, set City / Region / Country / country code (for example `Dallas`, `Texas`, `United States`, `US`), enable live lookups, click SAVE REGION, then TEST INTERNET. You can ask “search the web for…”, “what is the weather in…”, or “show top news”. Live news is grouped local, national and worldwide; city-level local news needs a city setting.


Speech output reads the answer as natural prose. Markdown decorations and emoji are not spoken; the original formatted response remains visible in the cockpit.
