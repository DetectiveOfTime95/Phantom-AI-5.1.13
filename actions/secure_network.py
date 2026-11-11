"""Secure outbound networking for Phantom-AI.

Public Internet traffic must use HTTPS with certificate and hostname validation
and TLS 1.2 or newer. Plain HTTP is accepted only for explicitly local services
(loopback Ollama) or an explicitly configured private-LAN Home Assistant host.
Redirects may never downgrade an HTTPS request to HTTP.
"""
from __future__ import annotations

import ipaddress
import socket
import ssl
from urllib.error import URLError
from urllib.parse import urlsplit, urljoin
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener


def create_tls_context() -> ssl.SSLContext:
    """Create a strict TLS context using the operating system trust store."""
    context = ssl.create_default_context()
    # Include the Python CA bundle in packaged builds while retaining the OS
    # trust store (useful for enterprise roots installed by the user).
    try:
        import certifi
        context.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


TLS_CONTEXT = create_tls_context()


def _host_is_loopback(host: str) -> bool:
    value = (host or "").strip().strip("[]").lower().rstrip(".")
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _address_is_private_local(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # Use explicit local ranges rather than ipaddress.is_private, which also
    # classifies documentation/test ranges as non-global on some Python builds.
    if address.is_loopback or address.is_link_local:
        return True
    if isinstance(address, ipaddress.IPv4Address):
        return any(address in network for network in (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
        ))
    return address in ipaddress.ip_network("fc00::/7")


def _host_is_private_or_loopback(host: str) -> bool:
    value = (host or "").strip().strip("[]").lower().rstrip(".")
    if value == "localhost":
        return True
    try:
        return _address_is_private_local(ipaddress.ip_address(value))
    except ValueError:
        pass
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(value, None, type=socket.SOCK_STREAM)
        }
        return bool(addresses) and all(_address_is_private_local(address) for address in addresses)
    except (OSError, ValueError):
        return False


def validate_outbound_url(
    value: str,
    *,
    allow_loopback_http: bool = False,
    allow_private_http: bool = False,
) -> str:
    """Validate URL transport before credentials or payloads are sent."""
    raw = str(value or "").strip()
    parts = urlsplit(raw)
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise ValueError("Network URL must use HTTPS and include a valid hostname.")
    if parts.username or parts.password:
        raise ValueError("Credentials must not be embedded in network URLs.")
    if parts.scheme == "http":
        if allow_loopback_http and _host_is_loopback(parts.hostname):
            return raw
        if allow_private_http and _host_is_private_or_loopback(parts.hostname):
            return raw
        raise ValueError("Unencrypted HTTP to Internet hosts is blocked. Use an HTTPS URL.")
    return raw


class _SecureRedirectHandler(HTTPRedirectHandler):
    def __init__(self, *, allow_loopback_http=False, allow_private_http=False, same_host_only=False):
        super().__init__()
        self.allow_loopback_http = allow_loopback_http
        self.allow_private_http = allow_private_http
        self.same_host_only = same_host_only

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urlsplit(req.full_url)
        target = urljoin(req.full_url, newurl)
        new = urlsplit(target)
        if old.scheme == "https" and new.scheme != "https":
            raise URLError("Blocked an HTTPS-to-HTTP redirect to protect the connection.")
        if self.same_host_only and (old.hostname or "").lower() != (new.hostname or "").lower():
            raise URLError("Blocked a cross-host redirect while forwarding a local-service credential.")
        validate_outbound_url(
            target,
            allow_loopback_http=self.allow_loopback_http,
            allow_private_http=self.allow_private_http,
        )
        return super().redirect_request(req, fp, code, msg, headers, target)


def secure_urlopen(
    request_or_url,
    *,
    timeout: float = 15,
    allow_loopback_http: bool = False,
    allow_private_http: bool = False,
    same_host_redirects: bool = False,
):
    """Open a URL with TLS verification and downgrade-safe redirects."""
    request = request_or_url if isinstance(request_or_url, Request) else Request(str(request_or_url))
    validate_outbound_url(
        request.full_url,
        allow_loopback_http=allow_loopback_http,
        allow_private_http=allow_private_http,
    )
    opener = build_opener(
        HTTPSHandler(context=TLS_CONTEXT),
        _SecureRedirectHandler(
            allow_loopback_http=allow_loopback_http,
            allow_private_http=allow_private_http,
            same_host_only=same_host_redirects,
        ),
    )
    return opener.open(request, timeout=timeout)


def secure_requests_session():
    """Requests session with certificate checks and TLS 1.2 minimum."""
    import requests
    from requests.adapters import HTTPAdapter

    class TLS12Adapter(HTTPAdapter):
        def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
            kwargs["ssl_context"] = create_tls_context()
            return super().init_poolmanager(connections, maxsize, block=block, **kwargs)

        def proxy_manager_for(self, proxy, **kwargs):
            kwargs["ssl_context"] = create_tls_context()
            return super().proxy_manager_for(proxy, **kwargs)

    session = requests.Session()
    session.verify = True
    session.trust_env = True
    session.mount("https://", TLS12Adapter())
    return session


def secure_request(method: str, url: str, *, timeout=20, **kwargs):
    """Send an HTTPS request; validate every redirect before following it."""
    import requests

    current_url = validate_outbound_url(url)
    current_method = str(method or "GET").upper()
    session = secure_requests_session()
    try:
        for hop in range(6):
            response = session.request(
                current_method,
                current_url,
                timeout=timeout,
                allow_redirects=False,
                **kwargs,
            )
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("Location")
            if not location:
                return response
            next_url = validate_outbound_url(urljoin(current_url, location))
            old_parts, new_parts = urlsplit(current_url), urlsplit(next_url)
            if old_parts.scheme == "https" and new_parts.scheme != "https":
                response.close()
                raise requests.exceptions.SSLError("Blocked HTTPS-to-HTTP redirect.")
            if hop == 5:
                response.close()
                raise requests.exceptions.TooManyRedirects("Too many secure redirects.")
            if response.status_code == 303 or (response.status_code in {301, 302} and current_method == "POST"):
                current_method = "GET"
                kwargs.pop("json", None)
                kwargs.pop("data", None)
            if (old_parts.hostname or "").lower() != (new_parts.hostname or "").lower():
                headers = dict(kwargs.get("headers") or {})
                for key in list(headers):
                    if key.lower() in {"authorization", "cookie", "proxy-authorization"}:
                        headers.pop(key, None)
                kwargs["headers"] = headers
            response.close()
            current_url = next_url
        raise requests.exceptions.TooManyRedirects("Too many secure redirects.")
    finally:
        # The response body is buffered by requests unless stream=True. This session
        # is deliberately short-lived so trust and proxy settings stay predictable.
        session.close()
