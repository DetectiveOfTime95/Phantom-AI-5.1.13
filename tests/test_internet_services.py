import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from actions import internet_services as internet


class FakeResponse:
    def __init__(self, content=b"", payload=None):
        self.content = content
        self._payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self._payload


class InternetServicesTests(unittest.TestCase):
    def test_intent_detection_weather_news_search(self):
        self.assertTrue(internet._is_weather_request("what is the weather in Dallas"))
        self.assertTrue(internet._is_news_request("show top news"))
        self.assertTrue(internet._is_search_request("search the web for Ollama updates"))
        self.assertTrue(internet._is_search_request("who is the current prime minister"))
        self.assertTrue(internet._is_search_request("what is the latest Ollama release"))
        self.assertFalse(internet._is_search_request("tell me a joke"))

    def test_weather_city_extraction(self):
        self.assertEqual(internet._extract_weather_city("weather in Dallas today"), "Dallas")
        self.assertEqual(internet._extract_weather_city("forecast for Toronto tomorrow"), "Toronto")

    def test_search_uses_secure_https_client_and_parses_rss(self):
        xml = b'<rss><channel><item><title>Example story</title><description>Story summary</description><link>https://example.com/story</link></item></channel></rss>'
        with patch.object(internet, "secure_request", return_value=FakeResponse(content=xml)) as request:
            result = internet.search_web("test query")
        self.assertEqual(result["provider"], "Bing Search RSS")
        self.assertEqual(result["results"][0]["title"], "Example story")
        self.assertTrue(request.call_args.args[1].startswith("https://"))

    def test_live_context_only_runs_for_online_intent(self):
        self.assertIsNone(internet.build_live_context("tell me a joke"))

    def test_weather_context_uses_provider_and_url(self):
        with patch.object(internet, "get_weather", return_value={"text": "Sunny, 20 C", "provider": "Open-Meteo", "url": "https://api.open-meteo.com/test"}):
            result = internet.build_live_context("weather in Paris")
        self.assertTrue(result["ok"])
        self.assertEqual(result["intent"], "weather")
        self.assertIn("Open-Meteo", result["provider"] or "")
        self.assertIn("https://api.open-meteo.com/test", result["sources"])

    def test_live_lookup_failure_is_explicit(self):
        with patch.object(internet, "search_web", side_effect=OSError("offline")):
            result = internet.build_live_context("search the web for current AI model updates")
        self.assertFalse(result["ok"])
        self.assertIn("Do not invent current facts", result["context"])

    def test_settings_save_validates_country_code(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(internet, "SETTINGS_FILE", Path(folder) / "internet_settings.json"), patch.object(internet, "CONFIG_DIR", Path(folder)):
                with self.assertRaisesRegex(ValueError, "two-letter ISO"):
                    internet.save_internet_settings({"countryCode": "USA"})
                saved = internet.save_internet_settings({"city": "Dallas", "country": "United States", "countryCode": "US", "enabled": True})
                self.assertEqual(saved["city"], "Dallas")
                loaded = internet.load_internet_settings()
                self.assertEqual(loaded["countryCode"], "US")


if __name__ == "__main__":
    unittest.main()
