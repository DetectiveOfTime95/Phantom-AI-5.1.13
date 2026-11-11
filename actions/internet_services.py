"""Live Internet tools for Phantom-AI.

All public requests go through actions.secure_network.secure_request, which
requires HTTPS, verifies certificates/hostnames and blocks downgrade redirects.
Ollama remains local; only a query and returned public information are sent to it.
"""
from __future__ import annotations

import html
import json
import locale
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from actions.secure_network import secure_request

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(__import__("os").environ.get("PHANTOM_CONFIG_DIR", BASE_DIR / "config"))
SETTINGS_FILE = CONFIG_DIR / "internet_settings.json"
USER_AGENT = "Phantom-AI/5.1.13 (Phantom Softworks desktop assistant)"


def _default_country() -> tuple[str, str]:
    try:
        current = (locale.getlocale()[0] or "").strip()
        names = {
            "united states": ("United States", "US"), "united kingdom": ("United Kingdom", "GB"),
            "canada": ("Canada", "CA"), "australia": ("Australia", "AU"),
            "new zealand": ("New Zealand", "NZ"), "india": ("India", "IN"),
            "ireland": ("Ireland", "IE"), "germany": ("Germany", "DE"),
            "france": ("France", "FR"), "spain": ("Spain", "ES"),
            "italy": ("Italy", "IT"), "japan": ("Japan", "JP"),
        }
        lowered = current.lower().replace("_", " ")
        for phrase, pair in names.items():
            if phrase in lowered:
                return pair
        match = re.search(r"^[a-z]{2}[_-]([A-Z]{2})$", current)
        if match:
            code = match.group(1).upper()
            code_names = {"US": "United States", "GB": "United Kingdom", "CA": "Canada", "AU": "Australia", "NZ": "New Zealand", "IN": "India", "IE": "Ireland", "DE": "Germany", "FR": "France", "ES": "Spain", "IT": "Italy", "JP": "Japan"}
            return code_names.get(code, code), code
    except Exception:
        pass
    return "", ""


def load_internet_settings() -> dict[str, Any]:
    country, country_code = _default_country()
    settings = {
        "enabled": True,
        "city": "",
        "region": "",
        "country": country,
        "countryCode": country_code,
        "allowLiveSearch": True,
        "allowLiveNews": True,
        "allowLiveWeather": True,
    }
    try:
        stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(stored, dict):
            for key in settings:
                if key in stored:
                    settings[key] = stored[key]
    except (OSError, ValueError, TypeError):
        pass
    settings["city"] = str(settings.get("city") or "").strip()[:100]
    settings["region"] = str(settings.get("region") or "").strip()[:100]
    settings["country"] = str(settings.get("country") or "").strip()[:100]
    settings["countryCode"] = str(settings.get("countryCode") or "").strip().upper()[:2]
    for key in ("enabled", "allowLiveSearch", "allowLiveNews", "allowLiveWeather"):
        settings[key] = bool(settings.get(key))
    return settings


def save_internet_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = load_internet_settings()
    if not isinstance(payload, dict):
        raise ValueError("Internet settings must be an object.")
    for key in current:
        if key in payload:
            current[key] = payload[key]
    current["city"] = str(current.get("city") or "").strip()[:100]
    current["region"] = str(current.get("region") or "").strip()[:100]
    current["country"] = str(current.get("country") or "").strip()[:100]
    raw_country_code = str(current.get("countryCode") or "").strip().upper()
    if raw_country_code and not re.fullmatch(r"[A-Z]{2}", raw_country_code):
        raise ValueError("Country code must be a two-letter ISO code, such as US, GB, or CA.")
    current["countryCode"] = raw_country_code
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(SETTINGS_FILE)
    return current


def _get_json(url: str, *, timeout: int = 12, headers: dict | None = None) -> dict:
    merged = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    response = secure_request("GET", url, timeout=timeout, headers=merged)
    response.raise_for_status()
    return response.json()


def _clean_text(value: Any, limit: int = 420) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def search_web(query: str, max_results: int = 7) -> dict[str, Any]:
    """Search the live web through Bing's HTTPS RSS endpoint (no API key)."""
    query = str(query or "").strip()[:300]
    if not query:
        raise ValueError("Enter a search query.")
    params = urlencode({"q": query, "format": "rss", "setlang": "en-us"})
    url = "https://www.bing.com/search?" + params
    response = secure_request(
        "GET", url, timeout=15,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"},
    )
    response.raise_for_status()
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise RuntimeError("The search provider returned an unreadable response.") from exc
    items = []
    for item in root.findall(".//item")[:max(1, min(int(max_results), 10))]:
        title = _clean_text(item.findtext("title"), 220)
        snippet = _clean_text(item.findtext("description"), 520)
        link = _clean_text(item.findtext("link"), 600)
        if title and link.startswith("https://"):
            items.append({"title": title, "snippet": snippet, "url": link})
    return {"query": query, "provider": "Bing Search RSS", "checkedAt": int(time.time()), "results": items}


_WEATHER_CODES = {
    0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 56: "freezing drizzle", 57: "heavy freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
    67: "heavy freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow",
    77: "snow grains", 80: "rain showers", 81: "moderate rain showers",
    82: "heavy rain showers", 85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm with hail",
}


def _geocode(city: str) -> dict:
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urlencode({"name": city, "count": 1, "language": "en", "format": "json"})
    payload = _get_json(url)
    results = payload.get("results") or []
    if not results:
        raise ValueError(f"I couldn't locate '{city}'. Try a city and country, for example 'Dallas, United States'.")
    return results[0]


def _nws_weather(lat: float, lon: float) -> dict | None:
    """Use the US National Weather Service when coordinates are in its area."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/geo+json, application/json"}
    try:
        point = _get_json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}", headers=headers, timeout=12)
        props = point.get("properties") or {}
        forecast_url = props.get("forecast")
        if not forecast_url or not str(forecast_url).startswith("https://api.weather.gov/"):
            return None
        forecast = _get_json(forecast_url, headers=headers, timeout=12)
        periods = ((forecast.get("properties") or {}).get("periods") or [])[:5]
        if not periods:
            return None
        lines = ["Source: US National Weather Service (NWS).", "Forecast:"]
        for period in periods:
            name = _clean_text(period.get("name"), 60)
            temp = period.get("temperature")
            unit = period.get("temperatureUnit") or "F"
            summary = _clean_text(period.get("shortForecast"), 100)
            wind = _clean_text(period.get("windSpeed"), 60)
            lines.append(f"- {name}: {temp}°{unit}, {summary}; wind {wind}.")
        return {"provider": "US National Weather Service", "text": "\n".join(lines), "url": forecast_url}
    except Exception:
        return None


def get_weather(city: str) -> dict[str, Any]:
    city = str(city or "").strip()[:120]
    if not city:
        settings = load_internet_settings()
        city = ", ".join(part for part in (settings["city"], settings["region"], settings["country"]) if part)
    if not city:
        raise ValueError("Tell me the city, or set your city in Console → ONLINE so I can retrieve local weather.")
    place = _geocode(city)
    lat, lon = float(place["latitude"]), float(place["longitude"])
    place_name = ", ".join(str(x) for x in (place.get("name"), place.get("admin1"), place.get("country")) if x)
    country_code = str(place.get("country_code") or "").upper()
    if country_code == "US":
        nws = _nws_weather(lat, lon)
        if nws:
            return {"location": place_name, "provider": nws["provider"], "url": nws["url"], "text": f"Weather for {place_name}\n{nws['text']}"}
    params = {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto", "forecast_days": 3,
        "temperature_unit": "fahrenheit" if country_code == "US" else "celsius",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urlencode(params)
    data = _get_json(url, timeout=15)
    current = data.get("current") or {}
    units = data.get("current_units") or {}
    daily = data.get("daily") or {}
    daily_units = data.get("daily_units") or {}
    temp_symbol = units.get("temperature_2m", "°C")
    daily_temp_symbol = daily_units.get("temperature_2m_max", temp_symbol)
    lines = [f"Current weather for {place_name} (local time {current.get('time', 'unknown')}):"]
    code = current.get("weather_code")
    lines.append(
        f"- Conditions: {_WEATHER_CODES.get(code, 'conditions unavailable')}; "
        f"temperature {current.get('temperature_2m')} {units.get('temperature_2m', '°C')}; "
        f"feels like {current.get('apparent_temperature')} {units.get('apparent_temperature', '°C')}; "
        f"humidity {current.get('relative_humidity_2m')}%; wind {current.get('wind_speed_10m')} {units.get('wind_speed_10m', 'km/h')}; "
        f"precipitation {current.get('precipitation')} {units.get('precipitation', 'mm')}."
    )
    dates = daily.get("time") or []
    for index, date in enumerate(dates[:3]):
        daily_code = (daily.get("weather_code") or [None] * 3)[index]
        high = (daily.get("temperature_2m_max") or [None] * 3)[index]
        low = (daily.get("temperature_2m_min") or [None] * 3)[index]
        rain = (daily.get("precipitation_probability_max") or [None] * 3)[index]
        lines.append(f"- {date}: {_WEATHER_CODES.get(daily_code, 'forecast unavailable')}; high {high}{daily_temp_symbol}, low {low}{daily_units.get('temperature_2m_min', daily_temp_symbol)}; precipitation chance {rain}%.")
    return {"location": place_name, "provider": "Open-Meteo", "url": url, "text": "\n".join(lines)}


def _gdelt_articles(query: str, country_code: str = "", limit: int = 5) -> list[dict]:
    search_query = query.strip()
    if country_code:
        search_query += f" sourcecountry:{country_code.upper()}"
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode({
        "query": search_query, "mode": "ArtList", "format": "json",
        "maxrecords": max(1, min(limit, 10)), "sort": "HybridRel", "timespan": "24h",
    })
    data = _get_json(url, timeout=18, headers={"Accept": "application/json"})
    output = []
    seen = set()
    for article in data.get("articles") or []:
        title = _clean_text(article.get("title"), 220)
        url_value = str(article.get("url") or "").strip()
        if not title or not url_value.startswith("https://") or url_value in seen:
            continue
        seen.add(url_value)
        output.append({
            "title": title,
            "source": _clean_text(article.get("domain") or article.get("sourcecountry") or "News source", 80),
            "seenByGdelt": str(article.get("seendate") or "")[:14],
            "url": url_value,
        })
        if len(output) >= limit:
            break
    return output


def get_top_news(*, city: str = "", region: str = "", country: str = "", country_code: str = "", limit: int = 5) -> dict[str, Any]:
    settings = load_internet_settings()
    city = str(city or settings.get("city") or "").strip()
    region = str(region or settings.get("region") or "").strip()
    country = str(country or settings.get("country") or "").strip()
    country_code = str(country_code or settings.get("countryCode") or "").strip().upper()
    sections: list[tuple[str, list[dict]]] = []
    errors = []
    if city:
        local_query = f'"{city}"' + (f' "{region}"' if region else "") + " (local OR community OR city)"
        try:
            sections.append(("LOCAL", _gdelt_articles(local_query, country_code, limit)))
        except Exception as exc:
            errors.append(f"Local: {str(exc)[:160]}")
    else:
        sections.append(("LOCAL", []))
    if country:
        national_query = f'"{country}" (national OR government OR economy OR politics OR breaking)'
    elif country_code:
        national_query = "(national OR government OR economy OR politics OR breaking)"
    else:
        national_query = "(national OR government OR economy OR politics OR breaking)"
    try:
        sections.append(("NATIONAL" + (f" — {country}" if country else ""), _gdelt_articles(national_query, country_code, limit)))
    except Exception as exc:
        errors.append(f"National: {str(exc)[:160]}")
    try:
        sections.append(("WORLDWIDE", _gdelt_articles('(world OR international OR global) (news OR politics OR conflict OR economy)', "", limit)))
    except Exception as exc:
        errors.append(f"Worldwide: {str(exc)[:160]}")
    return {"provider": "GDELT Global News Database", "checkedAt": int(time.time()), "sections": sections, "errors": errors}


def _is_weather_request(text: str) -> bool:
    value = text.lower()
    return any(term in value for term in ("weather", "forecast", "temperature outside", "temperature in ", "temperature today", "chance of rain", "will it rain", "humidity outside"))


def _is_news_request(text: str) -> bool:
    value = text.lower()
    return any(term in value for term in ("news", "headlines", "breaking stories", "top stories", "current events"))


def _is_search_request(text: str) -> bool:
    value = text.lower()
    explicit = ("search the web", "search online", "search the internet", "look up", "find online", "google", "web search", "browse the web")
    fresh = ("latest", "most recent", "recent", "recently", "current", "today's", "today’s", "right now", "as of today", "this week", "this month", "this year", "currently", "newest", "just announced", "latest version")
    return any(term in value for term in explicit + fresh)


def _extract_weather_city(text: str) -> str:
    match = re.search(r"\b(?:weather|forecast)\s+(?:in|for|at)\s+(.+?)(?:\s+(?:today|tonight|tomorrow|this week|this weekend))?[?.!]*$", text, flags=re.I)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip(" ,?.!")[:120]
    return ""


def build_live_context(text: str) -> dict[str, Any] | None:
    """Fetch live Internet evidence for explicit/current-information questions."""
    text = str(text or "").strip()
    if not text:
        return None
    settings = load_internet_settings()
    if not settings.get("enabled"):
        return None
    intent = None
    payload_text = ""
    sources: list[str] = []
    try:
        explicit_search = any(term in text.lower() for term in ("search the web", "search online", "search the internet", "web search", "browse the web"))
        if _is_weather_request(text) and settings.get("allowLiveWeather"):
            intent = "weather"
            result = get_weather(_extract_weather_city(text))
            payload_text = result["text"]
            sources.append(result["url"])
            provider = result["provider"]
        elif _is_news_request(text) and settings.get("allowLiveNews") and not explicit_search:
            intent = "news"
            result = get_top_news(limit=5)
            provider = result["provider"]
            parts = []
            for name, articles in result["sections"]:
                parts.append(f"{name}:")
                if not articles:
                    if name == "LOCAL":
                        parts.append("No local city is configured or no local stories were returned.")
                    else:
                        parts.append("No matching articles were returned.")
                for article in articles:
                    parts.append(f"- {article['title']} | {article['source']} | GDELT indexed {article['seenByGdelt']} | {article['url']}")
                    sources.append(article["url"])
            if result.get("errors"):
                parts.append("Provider notices: " + "; ".join(result["errors"]))
            payload_text = "\n".join(parts)
            if not settings.get("city"):
                payload_text += "\nLocal stories are limited until the user sets a city in Console → ONLINE."
        elif _is_search_request(text) and settings.get("allowLiveSearch"):
            intent = "web_search"
            query = re.sub(r"^(?:please\s+)?(?:search(?: the web| online| the internet)?|look up|find online|google|browse the web)\s*(?:for|about)?\s*", "", text, flags=re.I).strip()
            if not query:
                query = text
            result = search_web(query, max_results=7)
            provider = result["provider"]
            payload_text = "\n".join(f"- {x['title']}\n  {x['snippet']}\n  {x['url']}" for x in result["results"])
            sources = [x["url"] for x in result["results"]]
            if not payload_text:
                payload_text = "The live search provider returned no results."
        else:
            return None
        return {
            "intent": intent, "ok": True, "provider": provider,
            "context": payload_text[:15000], "sources": sources[:20],
            "checkedAt": int(time.time()),
        }
    except Exception as exc:
        return {
            "intent": intent or ("weather" if _is_weather_request(text) else "news" if _is_news_request(text) else "web_search"),
            "ok": False, "provider": "Internet service", "context": f"Live Internet lookup failed: {str(exc)[:300]}. Do not invent current facts; tell the user that the online lookup failed.",
            "sources": [], "error": str(exc)[:300], "checkedAt": int(time.time()),
        }
