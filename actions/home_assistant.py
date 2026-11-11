"""Home Assistant bridge for Phantom-AI.

A Home Assistant long-lived access token is stored with Windows DPAPI when the
app runs on Windows. Environment variables remain available for development.
Only an explicit allow-list of service/domain combinations is exposed.
"""
from __future__ import annotations

import base64
import ctypes
import ipaddress
import json
import os
import socket
import sys
from ctypes import wintypes
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request

from actions.secure_network import secure_urlopen

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("PHANTOM_CONFIG_DIR", BASE_DIR / "config"))
CONFIG_FILE = CONFIG_DIR / "home_assistant.json"

SAFE_SERVICES = {
    "light": {"turn_on", "turn_off", "toggle"},
    "switch": {"turn_on", "turn_off", "toggle"},
    "fan": {"turn_on", "turn_off", "toggle"},
    "climate": {"turn_on", "turn_off"},
    "cover": {"open_cover", "close_cover", "stop_cover"},
    "lock": {"lock", "unlock"},
    "alarm_control_panel": {"alarm_arm_home", "alarm_arm_away", "alarm_disarm"},
    "siren": {"turn_on", "turn_off"},
}
SENSITIVE_ACTIONS = {
    ("lock", "unlock"),
    ("alarm_control_panel", "alarm_disarm"),
    ("cover", "open_cover"),
    ("siren", "turn_on"),
}


def _dpapi_protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("Secure token storage requires Windows DPAPI. Use environment variables for development.")

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    source_buffer = ctypes.create_string_buffer(data)
    source = DATA_BLOB(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    target = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptProtectData(ctypes.byref(source), "Phantom-AI Home Assistant token", None, None, None, 0, ctypes.byref(target)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("Secure token storage requires Windows DPAPI.")

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    source_buffer = ctypes.create_string_buffer(data)
    source = DATA_BLOB(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    target = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def _normalise_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Enter a valid Home Assistant URL, such as https://homeassistant.example.com (HTTPS is required for remote servers; local private-LAN HTTP may be used only on a trusted home network).")
    if parts.query or parts.fragment:
        raise ValueError("The Home Assistant URL must not contain query parameters or a fragment.")
    host = parts.hostname.lower()
    if parts.scheme == "http":
        local_ok = host in {"localhost", "homeassistant", "homeassistant.local"}
        try:
            local_ok = local_ok or ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
        except ValueError:
            try:
                addresses = socket.getaddrinfo(host, None)
                local_ok = local_ok or all(
                    ipaddress.ip_address(item[4][0]).is_private or ipaddress.ip_address(item[4][0]).is_loopback
                    for item in addresses
                )
            except OSError:
                pass
        if not local_ok:
            raise ValueError("Use HTTPS for a Home Assistant server outside your local network.")
    return url


def _read_config() -> dict:
    url = os.environ.get("PHANTOM_HOME_ASSISTANT_URL", "").strip()
    token = os.environ.get("PHANTOM_HOME_ASSISTANT_TOKEN", "").strip()
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            url = str(saved.get("url") or url)
            protected = saved.get("token_dpapi")
            if protected and sys.platform == "win32":
                token = _dpapi_unprotect(base64.b64decode(protected)).decode("utf-8")
        except Exception:
            # Environment overrides remain usable if the settings file is corrupt.
            pass
    return {"url": url.rstrip("/"), "token": token}


def save_config(url: str, token: str) -> dict:
    clean_url = _normalise_url(url)
    token = str(token or "").strip()
    if len(token) < 20:
        raise ValueError("Paste a valid Home Assistant long-lived access token.")
    protected = base64.b64encode(_dpapi_protect(token.encode("utf-8"))).decode("ascii")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"url": clean_url, "token_dpapi": protected}, indent=2), encoding="utf-8")
    return {"connected": True, "url": clean_url, "tokenStoredSecurely": True}


def status() -> dict:
    cfg = _read_config()
    return {"configured": bool(cfg["url"] and cfg["token"]), "url": cfg["url"], "connected": False}


def _request(path: str, method: str = "GET", payload: dict | None = None, timeout: int = 12):
    cfg = _read_config()
    if not cfg["url"] or not cfg["token"]:
        raise RuntimeError("Home Assistant is not configured. Open Console > HOME and connect your server.")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(
        cfg["url"] + "/api/" + path.lstrip("/"),
        data=body,
        headers={"Authorization": "Bearer " + cfg["token"], "Content-Type": "application/json"},
        method=method,
    )
    try:
        with secure_urlopen(req, timeout=timeout, allow_private_http=True, same_host_redirects=True) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else None
    except HTTPError as exc:
        detail = exc.read(500).decode("utf-8", "replace")
        if exc.code == 401:
            raise RuntimeError("Home Assistant rejected the token. Create a new long-lived access token.") from exc
        raise RuntimeError(f"Home Assistant returned HTTP {exc.code}: {detail[:200]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Home Assistant: {exc.reason}") from exc


def test_connection() -> dict:
    config = _read_config()
    if not config["url"] or not config["token"]:
        return {"ok": False, "error": "not_configured"}
    result = _request("", timeout=8)
    return {"ok": True, "message": str((result or {}).get("message") or "API connection successful.")}


def list_entities() -> list[dict]:
    states = _request("states")
    result = []
    for item in states if isinstance(states, list) else []:
        entity_id = str(item.get("entity_id") or "")
        domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
        if domain not in SAFE_SERVICES and domain not in {"camera", "binary_sensor", "sensor"}:
            continue
        attrs = item.get("attributes") or {}
        result.append({
            "entityId": entity_id,
            "domain": domain,
            "name": str(attrs.get("friendly_name") or entity_id),
            "state": str(item.get("state") or "unknown"),
            "supportedServices": sorted(SAFE_SERVICES.get(domain, set())),
        })
    return sorted(result, key=lambda x: (x["domain"], x["name"].lower()))


def resolve_entity(name: str, allowed_domains: set[str] | None = None) -> dict | None:
    needle = str(name or "").strip().lower()
    if not needle:
        return None
    entities = list_entities()
    candidates = [x for x in entities if allowed_domains is None or x["domain"] in allowed_domains]
    exact = [x for x in candidates if x["entityId"].lower() == needle or x["name"].lower() == needle]
    if exact:
        return exact[0]
    matches = [x for x in candidates if needle in x["name"].lower() or needle in x["entityId"].lower()]
    if len(matches) == 1:
        return matches[0]
    # Do not guess when two rooms/devices share similar names.
    return None


def call_service(entity_id: str, service: str, confirmed: bool = False) -> str:
    entity_id = str(entity_id or "").strip().lower()
    service = str(service or "").strip().lower()
    if "." not in entity_id:
        raise ValueError("A valid Home Assistant entity ID is required.")
    domain = entity_id.split(".", 1)[0]
    if service not in SAFE_SERVICES.get(domain, set()):
        raise ValueError("That Home Assistant domain/service is not on Phantom's allow-list.")
    if (domain, service) in SENSITIVE_ACTIONS and not confirmed:
        raise PermissionError("This action requires an explicit confirmation.")
    _request(f"services/{domain}/{service}", method="POST", payload={"entity_id": entity_id}, timeout=15)
    return f"Sent {service.replace('_', ' ')} to {entity_id}."


def try_handle_command(text: str) -> str | None:
    """Parse narrow home commands; never let a model invent an entity or service."""
    import re

    raw = str(text or "").strip()
    lower = raw.lower()
    if re.search(r"\b(home|home assistant|smart home|house)\b", lower) and re.search(r"\b(devices|status|what is connected|list)\b", lower):
        entities = list_entities()
        if not entities:
            return "I did not find any supported devices in Home Assistant."
        return "Home devices: " + "; ".join(f"{x['name']} ({x['domain']}) is {x['state']}" for x in entities[:18])

    # Confirmation is two-step and matches the exact device and intended action.
    pending = _PENDING
    if pending and pending.get("confirm_text") and raw.casefold() == pending["confirm_text"].casefold():
        if pending["expires"] < __import__("time").time():
            _PENDING.clear()
            return "That confirmation expired. Please issue the home command again."
        _PENDING.clear()
        return call_service(pending["entity_id"], pending["service"], confirmed=True)

    patterns = [
        (r"^(?:please\s+)?(?:turn|switch)\s+(?:the\s+)?(.+?)\s+(on|off)$", "power_suffix"),
        (r"^(?:please\s+)?(?:turn|switch)\s+(on|off)\s+(?:the\s+)?(.+)$", "power_prefix"),
        (r"^(?:please\s+)?(lock|unlock|arm|disarm|open|close)\s+(?:the\s+)?(.+)$", "security"),
    ]
    kind = None
    match = None
    for pattern, label in patterns:
        match = re.match(pattern, lower)
        if match:
            kind = label
            break
    if not match:
        return None

    if kind == "power_suffix":
        target, action = match.group(1), match.group(2)
        services = {"on": "turn_on", "off": "turn_off"}
        allowed = {"light", "switch", "fan", "climate", "siren"}
        service = services[action]
    elif kind == "power_prefix":
        action, target = match.group(1), match.group(2)
        service = {"on": "turn_on", "off": "turn_off"}[action]
        allowed = {"light", "switch", "fan", "climate", "siren"}
    else:
        action, target = match.group(1), match.group(2)
        if action in {"open", "close"} and not any(word in target for word in ("garage", "gate", "door", "cover", "shutter")):
            return None
        domain_service = {
            "lock": ("lock", "lock"), "unlock": ("lock", "unlock"),
            "arm": ("alarm_control_panel", "alarm_arm_away"),
            "disarm": ("alarm_control_panel", "alarm_disarm"),
            "open": ("cover", "open_cover"), "close": ("cover", "close_cover"),
        }
        domain, service = domain_service[action]
        allowed = {domain}

    entity = resolve_entity(target, allowed)
    if not entity:
        return f"I could not identify one unambiguous Home Assistant device named '{target}'. Check Console > HOME > DISCOVER DEVICES."
    sensitive = (entity["domain"], service) in SENSITIVE_ACTIONS
    if sensitive:
        confirm_text = f"CONFIRM {action.upper()} {entity['name'].upper()}"
        _PENDING.clear()
        _PENDING.update({
            "entity_id": entity["entityId"], "service": service,
            "confirm_text": confirm_text,
            "expires": __import__("time").time() + 45,
        })
        return f"This will {service.replace('_', ' ')} {entity['name']}. For safety, say or type exactly: {confirm_text}. This confirmation expires in 45 seconds."
    return call_service(entity["entityId"], service, confirmed=True)


_PENDING: dict = {}
