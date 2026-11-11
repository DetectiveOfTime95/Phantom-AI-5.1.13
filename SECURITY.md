# Phantom-AI Network Security

- Public Internet API calls use HTTPS with certificate-chain and hostname verification; TLS 1.2 is the minimum. HTTPS-to-HTTP redirects are rejected.
- The Electron renderer Content Security Policy permits Internet connections over HTTPS/WSS only, plus the loopback-only local backend and Ollama endpoints.
- The Python backend binds to 127.0.0.1 by default and requires its per-launch local API token on protected routes. Do not expose port 8770 to the LAN or Internet.
- Ollama defaults to http://127.0.0.1:11434. This is intentionally local-only traffic on the same computer, not an Internet connection. A remote Ollama server must use HTTPS.
- Home Assistant may use HTTP only when its hostname resolves to a private/local network. For connections over the Internet, configure HTTPS with a certificate trusted by Windows/Python. Do not disable certificate verification or use self-signed certificates without installing the issuing CA into the trusted store.
- Edge TTS uses its TLS-protected Microsoft speech WebSocket. Offline Vosk recognition does not send microphone audio to the Internet.
- Browser-agent navigations and inspected public sites also require HTTPS; public HTTP requests and HTTPS-to-HTTP redirects are blocked.
- DNS lookups still use the operating system resolver unless the user configures encrypted DNS in Windows/router settings. This is not a VPN or a whole-device encrypted tunnel.
- No TLS verification bypass, ignore-certificate-errors switch, or embedded proxy credential is configured.

## Network indicator

The cockpit's **Encrypted internet** indicator probes Cloudflare and then Google using verified HTTPS. It reports the negotiated TLS version when available. This verifies a reachable TLS endpoint; it does not guarantee every network, DNS, proxy, or remote service will be available.
