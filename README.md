# Phantom-AI 5.1.13 for Windows

Phantom-AI is a Windows desktop assistant built with Electron and a local Python backend. It uses Ollama for local language-model inference, an original British-style assistant voice, and Home Assistant as the supported smart-home integration layer. Your supplied Phantom ghost artwork is used for the application icon and UI logo. The Windows application metadata identifies the publisher/company as Phantom Softworks™.

## No paywall, account, activation, or license file

Phantom-AI now starts directly into the cockpit. It does not require a user account, payment, activation code, license file, or license manager. All installed features are available locally.

The optional monthly and yearly Stripe Payment Links remain in the **SUPPORT** dialog as voluntary support links only. Paying through them does not unlock features, and the app does not check payment status. There is no local payment server or Stripe secret key in the project. Enforcing paid subscriptions while also having no server and no local entitlement/license mechanism is not possible; this build intentionally chooses unrestricted local access.

## Phantom Softworks community

Join the official Discord server: https://discord.gg/VNEjTK7fYP. The app includes a **DISCORD** button in the cockpit and a matching link in the SUPPORT dialog.

## What is included

- **Local AI:** first-run setup checks for Ollama, offers to install the official Windows installer, verifies its Authenticode signature, starts Ollama, and pulls `qwen3:4b` if it is not already installed. Chat inference stays local to Ollama.
- **Wake word:** switch **VOICE: ON**, allow microphone permission, and say “Hey Phantom” followed by your prompt. Saying only “Hey Phantom” opens a 10-second command window. The listener tolerates split recognition results. Recognition runs through a local Vosk model. The approximately 40 MB English model downloads once on first use; thereafter, voice recognition works offline and does not call a browser speech-recognition service.
- **Voice:** Microsoft Edge TTS only, using an original polished British male assistant delivery (`en-GB-RyanNeural`) with precise diction, measured pacing, and a slightly lower register, inspired by cinematic digital assistants without copying an actor or character recording. Voice generation requires an internet connection; Windows speech synthesis is used as a fallback if the Edge voice service is unreachable. It does not copy an actor performance.
- **Smart home:** connect Home Assistant, discover supported devices, control lights/switches/fans/climate devices, and use voice/text commands. Unlocking a lock, disarming an alarm, opening a garage/gate/cover, or activating a siren requires an exact second confirmation. Camera entities are listed as status-only.
- **Windows builds:** the builder creates an NSIS installer and portable EXE with the uploaded Phantom icon.

## Build the Windows executable

On Windows 10/11 x64, install **Node.js 22.13 or newer** and **Python 3.12 x64**. Extract this project and double-click `BUILD-PHANTOM-AI.bat` (or `build-windows.bat`). The PowerShell-based builder creates a Python virtual environment, installs dependencies, runs the wake-word and offline-voice regression tests, builds the backend, and runs electron-builder. No billing service or license keys are initialized.

Build outputs are written to `release/`:

- `Phantom-AI Setup 5.1.13.exe` — interactive NSIS installer
- `Phantom-AI Portable 5.1.13.exe` — portable executable

The Windows executable is built locally on your Windows PC. No GitHub account, cloud runner, repository upload, billing service, or license keys are required.

## Voice network troubleshooting

- Test output speech with **Console → VOICE → TEST EDGE VOICE**. The test reports whether Microsoft Edge TTS connected; it will not report success if Windows fallback speech was used.
- Edge TTS needs outbound HTTPS/WebSocket access on TCP port 443 to `speech.platform.bing.com`. Check Windows Firewall, antivirus web protection, and any corporate proxy if the test fails.
- Speech recognition uses a local Vosk model and the Windows microphone through the bundled PortAudio interface. On first use, allow Phantom-AI to download the English model over HTTPS from the official Vosk model host (with a public model mirror as backup). Thereafter, recognition is offline. If setup fails, the cockpit reports whether the issue is a missing dependency, model download, or microphone device. The small English model is about 40 MB and uses the Apache 2.0 license (official model list: https://alphacephei.com/vosk/models). The recognizer now reads the selected microphone’s native sample rate (commonly 44.1 or 48 kHz) instead of forcing 16 kHz, avoiding unsupported-device-rate errors.
- Closing the main cockpit exits Phantom-AI and shuts down its helper windows and local backend. A second launch should either restore the running instance or start cleanly after the first instance exits.

## First launch

1. Launch Phantom-AI. It opens directly; no account or activation is needed.
2. Accept the Ollama setup prompt to install Ollama and download `qwen3:4b` if they are not already installed.
3. Press **VOICE: ON**, allow microphone access, then say “Hey Phantom” followed by your command. Voice listening can be turned off at any time. You can also type prompts.
4. Open **Console → HOME** to connect Home Assistant. Generate a long-lived access token in your Home Assistant profile and paste it into the connection form. The token is encrypted at rest with Windows DPAPI.
5. The **SUPPORT** button opens optional Stripe monthly/yearly support links. These do not affect app access.

## Security

- The Stripe live secret and restricted keys previously pasted into chat are exposed. Revoke/rotate them in Stripe. Phantom-AI uses only your hosted Payment Links and does not need Stripe secret keys.
- Do not put private API keys in renderer HTML or package them inside the executable.
- Review Home Assistant permissions carefully. Prefer dedicated Home Assistant users/tokens with only the integrations and entities Phantom-AI needs.
- The Home Assistant bridge exposes a restricted service allow-list; sensitive services require an exact confirmation, but Home Assistant permissions remain the ultimate security boundary.

## Project layout

- `electron/` — desktop main process, preload, cockpit UI, and renderer assets
- `bridge_backend.py`, `actions/` — local API, assistant and smart-home bridge
- `scripts/setup-ollama.ps1` — first-run Ollama setup
- `build/phantom.ico`, `electron/renderer/assets/` — application icon and logo artwork
- `tests/wake-word.test.cjs` — wake-word parser tests

## Encrypted Internet connectivity

Phantom-AI 5.1.13 requires verified HTTPS for public Internet API traffic, uses TLS 1.2 or newer, validates server certificates and hostnames, and blocks HTTPS-to-HTTP redirects. The cockpit shows an **Encrypted internet** status. Local Ollama and the desktop backend use loopback HTTP because they run on the same computer; remote Ollama and remote Home Assistant connections must use HTTPS.

The backend remains bound to `127.0.0.1`; do not expose port `8770` publicly. Home Assistant over HTTP is supported only for a private local network and is not encrypted across that LAN. Use HTTPS for remote access. This is TLS encryption for Phantom-AI service traffic, not a VPN or a whole-PC encrypted tunnel; DNS continues to use the Windows/router resolver unless encrypted DNS is enabled there.

## Build diagnostics

The Windows builder verifies Python 3.12 x64, recreates an incompatible old `.venv`, runs tests using that verified environment, and saves a complete log in `build-logs/`. If a build still fails, share the newest `build-logs/build-*.log` file. Do not share API keys or private config files. See `BUILD_TROUBLESHOOTING.md`.



## Direct Internet intelligence (5.1.13)

Live Internet features are enabled by default and are part of the normal Phantom-AI chat flow for explicit searches, current-information lookups, weather, and news. Results are fetched by the Python backend over validated HTTPS and supplied as source-linked context to the local Ollama model. Ollama remains the reasoning engine and runs on the user's computer; only the specific user query and retrieved public web data are used for the online lookup. Ordinary prompts that do not need current information remain local.

- **Live web search:** Bing Search RSS, no Gemini API key required.
- **Weather:** US National Weather Service (NWS) when a US location is requested; Open-Meteo global forecast service elsewhere or as a fallback.
- **News:** GDELT Global News Database, grouped LOCAL, NATIONAL, WORLDWIDE. Configure city, region, country and country code in Console → ONLINE.
- **Online settings:** Console → ONLINE can enable/disable live lookups, set the news/weather region, and test actual search-provider reachability.
- **Transport:** all public provider requests use certificate-validated HTTPS/TLS via `actions.secure_network`; redirects cannot downgrade to HTTP.
- If a live lookup fails, Phantom-AI passes an explicit failure notice to Ollama and instructs it not to fabricate current facts.

This is direct application-level Internet access for the features listed above; it does not tunnel all PC traffic or bypass a firewall/proxy. A configured firewall, proxy, DNS policy, or corporate network may still block a provider.


### Natural speech output

The on-screen answer retains its Markdown and emoji formatting. The speech path creates a separate clean spoken copy: emphasis markers and literal asterisks are removed, emoji are skipped, Markdown links are spoken by label, URLs are omitted, and fenced code is replaced with a brief note that code is displayed on screen. Both Edge TTS and the browser fallback use the clean spoken copy.


### Automatic online lookups

Phantom-AI automatically performs a live lookup for weather/forecast questions, news/headline requests, explicit web searches, and questions marked by current-time wording such as “current”, “latest”, “most recent”, “today”, “right now”, and “this week”. The returned HTTPS results are passed to Ollama as grounded context with source URLs. General conversation stays local unless an online lookup is requested or the wording clearly asks for up-to-date facts.


### Try these online commands

- “Search the web for the latest Ollama release.”
- “Who is the current prime minister of Canada?”
- “What is the weather in Dallas, Texas?” (or set your city in Console → ONLINE and ask “What is the weather?”)
- “Show me today's local, national, and worldwide news.”

The online service retrieves public information over HTTPS and passes the result plus source links to Ollama. Internet access is used for lookups; local reasoning, history, and normal chat remain on the PC.
