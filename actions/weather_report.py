"""Live weather action powered by national/global HTTPS weather services."""
from actions.internet_services import get_weather


def weather_action(parameters: dict, player=None, session_memory=None):
    params = parameters or {}
    city = str(params.get("city") or "").strip()
    try:
        result = get_weather(city)
        message = result["text"] + f"\nSource: {result['provider']} — {result['url']}"
    except Exception as exc:
        message = f"I couldn't retrieve live weather: {str(exc)[:240]}"
    if player:
        try:
            player.write_log(f"Phantom-AI: {message}")
        except Exception:
            pass
    if session_memory:
        try:
            session_memory.set_last_search(query=f"weather in {city or 'configured location'}", response=message)
        except Exception:
            pass
    return message
