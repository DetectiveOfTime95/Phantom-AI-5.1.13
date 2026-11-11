"""Live web search action for Phantom-AI (no API key required)."""
from actions.internet_services import search_web


def web_search(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    query = str(params.get("query") or "").strip()
    mode = str(params.get("mode") or "search").lower()
    items = params.get("items") or []
    aspect = str(params.get("aspect") or "general")
    if not query and not items:
        return "Please provide a search query, sir."
    try:
        if mode == "compare" and items:
            sections = []
            for item in items[:6]:
                data = search_web(f"{item} {aspect}", max_results=3)
                sections.append(f"{item}:\n" + "\n".join(f"- {r['title']}: {r['snippet']} ({r['url']})" for r in data["results"]))
            return "Live comparison from Bing Search:\n\n" + "\n\n".join(sections)
        data = search_web(query, max_results=int(params.get("max_results") or 7))
        if not data["results"]:
            return f"No live web results were returned for: {query}"
        lines = [f"Live web results for: {query} (via {data['provider']})"]
        for index, item in enumerate(data["results"], 1):
            lines.append(f"{index}. {item['title']}\n   {item['snippet']}\n   {item['url']}")
        return "\n\n".join(lines)
    except Exception as exc:
        return f"Live web search failed: {str(exc)[:260]}"
