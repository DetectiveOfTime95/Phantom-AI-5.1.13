import sys
import types
import unittest
from unittest.mock import patch

import phantom_voice


class FakeCommunicate:
    last_kwargs = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        type(self).last_kwargs = kwargs

    async def stream(self):
        yield {"type": "WordBoundary", "data": {}}
        yield {"type": "audio", "data": b"fake-mp3-data"}


class PhantomEdgeVoiceTests(unittest.TestCase):
    def test_status_reports_refined_edge_voice(self):
        with patch.object(phantom_voice.importlib.util, "find_spec", return_value=object()):
            status = phantom_voice.status()
        self.assertEqual(status["provider"], "microsoft-edge-tts")
        self.assertEqual(status["model"], "en-GB-RyanNeural")
        self.assertTrue(status["requiresInternet"])
        self.assertTrue(status["ready"])
        self.assertIn("British", status["persona"])

    def test_synthesis_returns_mp3_from_edge(self):
        fake_module = types.SimpleNamespace(Communicate=FakeCommunicate)
        with patch.object(phantom_voice.importlib.util, "find_spec", return_value=object()):
            with patch.dict(sys.modules, {"edge_tts": fake_module}):
                audio, content_type = phantom_voice.synthesize_audio("Hello from Phantom.")
        self.assertEqual(audio, b"fake-mp3-data")
        self.assertEqual(content_type, "audio/mpeg")

    def test_speech_copy_strips_markdown_and_emoji_before_edge_tts(self):
        fake_module = types.SimpleNamespace(Communicate=FakeCommunicate)
        with patch.object(phantom_voice.importlib.util, "find_spec", return_value=object()):
            with patch.dict(sys.modules, {"edge_tts": fake_module}):
                phantom_voice.synthesize_audio("**Hello, sir.** 🚀 ✅")
        self.assertEqual(FakeCommunicate.last_kwargs["text"], "Hello, sir.")
        self.assertNotIn("*", FakeCommunicate.last_kwargs["text"])
        self.assertNotIn("🚀", FakeCommunicate.last_kwargs["text"])

    def test_empty_text_is_rejected(self):
        with self.assertRaises(ValueError):
            phantom_voice.synthesize_audio("  ")

    def test_voice_settings_are_deliberate_and_lower_pitched(self):
        with patch.dict("os.environ", {"PHANTOM_EDGE_VOICE": "en-GB-RyanNeural", "PHANTOM_EDGE_RATE": "-7%", "PHANTOM_EDGE_PITCH": "-10Hz"}):
            settings = phantom_voice._settings()
        self.assertEqual(settings["voice"], "en-GB-RyanNeural")
        self.assertEqual(settings["rate"], "-7%")
        self.assertEqual(settings["pitch"], "-10Hz")


if __name__ == "__main__":
    unittest.main()
