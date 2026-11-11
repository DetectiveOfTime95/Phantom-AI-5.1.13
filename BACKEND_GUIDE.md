# Phantom-AI local backend

The desktop renderer calls the local Python backend at `http://127.0.0.1:8770`. The backend's Phantom chat/status, text-to-speech and Home Assistant routes reject non-loopback clients. Do not expose this port to the public internet.

## Ollama

The desktop application defaults to `http://127.0.0.1:11434` and `qwen3:4b`. On first launch, an opt-in setup routine downloads the official Ollama Windows installer if needed, checks its Authenticode signature, launches it, waits for the local API, and pulls the model. You can also install Ollama manually from https://ollama.com/download/windows and run `ollama pull qwen3:4b`.

The desktop process sets `PHANTOM_OLLAMA_ONLY=1`, so ordinary AI chat is local-only. When Ollama is unavailable, Phantom reports that the model is unavailable rather than sending the chat to a configured cloud provider. Some explicit web/search integrations already present in the app will of course use their respective online services.

## Local voice

`phantom_voice.py` uses Microsoft Edge TTS only, with the `en-GB-RyanNeural` voice and a measured speaking rate/pitch for an original polished British-style assistant persona. An internet connection is required. The Python package is included in `requirements.txt` and collected explicitly by `backend.spec` so the installed Windows app has the same voice runtime as development. If the online Edge TTS service cannot be reached, the renderer falls back to Windows/browser speech synthesis and logs the specific network error.

## Home Assistant

- `GET /api/phantom/home/status` — connection status
- `GET /api/phantom/home/entities` — discover supported entities
- `POST /api/phantom/home/connect` — validate and securely save the URL/token
- `POST /api/phantom/home/service` — invoke an allow-listed service

On Windows, the Home Assistant long-lived access token is encrypted using DPAPI before being written to the app's per-user configuration directory. Only the allow-listed `light`, `switch`, `fan`, `climate`, `cover`, `lock`, `alarm_control_panel`, and `siren` service/domain combinations are available. Lock unlock, alarm disarm, cover open and siren activation require an exact second confirmation. Sensors and cameras are read-only/status-only.

## Conversation history

The local chat route stores conversation messages in SQLite under the app-specific backend config directory. Model prompts and local chat messages are sent to the local Ollama API for inference.


## Encrypted network policy (5.1.13)

All public Internet requests use verified HTTPS with TLS 1.2 or newer; public HTTP and HTTPS-to-HTTP redirects are blocked. The app's local backend and Ollama default to loopback HTTP on the same machine and are not exposed as Internet services. Configure a remote Ollama endpoint using HTTPS. Home Assistant on a private LAN may use HTTP for compatibility, but that LAN traffic is not encrypted; for remote access use HTTPS with a certificate trusted by the computer.
