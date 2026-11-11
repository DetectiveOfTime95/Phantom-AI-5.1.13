import unittest
import tempfile
import zipfile
import urllib.request
from pathlib import Path
from unittest.mock import patch

from actions.offline_speech import OfflineSpeechEngine, MODEL_NAME, ensure_model, resolve_input_device_config


class OfflineSpeechEngineTests(unittest.TestCase):
    def test_status_is_local_and_offline_after_setup(self):
        engine = OfflineSpeechEngine()
        status = engine.status()
        self.assertEqual(status["provider"], "vosk-local")
        self.assertEqual(status["modelName"], MODEL_NAME)
        self.assertFalse(status["requiresInternet"])
        self.assertTrue(status["offlineAfterModelDownload"])

    def test_transcripts_are_queued_and_consumed_once(self):
        engine = OfflineSpeechEngine()
        engine._push_event("hey phantom turn on the lights")
        first = engine.status(consume_events=True)
        second = engine.status(consume_events=True)
        self.assertEqual(first["events"][0]["text"], "hey phantom turn on the lights")
        self.assertEqual(second["events"], [])

    def test_duplicate_transcript_is_debounced(self):
        engine = OfflineSpeechEngine()
        engine._push_event("hey phantom")
        engine._push_event("hey phantom")
        status = engine.status()
        self.assertEqual(len(status["events"]), 1)

    def test_model_download_and_install_from_local_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive_path = root / "test-model.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(f"{MODEL_NAME}/am/final.mdl", "fake-model")
                archive.writestr(f"{MODEL_NAME}/conf/mfcc.conf", "fake-config")
            app_data = root / "app-data"
            with patch("actions.offline_speech._app_data_dir", return_value=app_data):
                with patch("actions.offline_speech.MODEL_URLS", (archive_path.as_uri(),)), patch("actions.offline_speech.MIRROR_SHA256", ""), patch("actions.offline_speech.secure_urlopen", side_effect=lambda request, timeout=75: urllib.request.urlopen(request, timeout=timeout)):
                    installed = ensure_model()
            self.assertTrue((installed / "am" / "final.mdl").is_file())
            self.assertTrue((installed / "conf" / "mfcc.conf").is_file())

    def test_input_device_uses_supported_native_sample_rate(self):
        class FakeDefault:
            device = (4, 2)
        class FakeSoundDevice:
            default = FakeDefault()
            @staticmethod
            def query_devices(device, kind):
                assert device == 4
                assert kind == "input"
                return {"name": "USB Headset", "max_input_channels": 2, "default_samplerate": 48000.0}
        device, sample_rate, name = resolve_input_device_config(FakeSoundDevice)
        self.assertEqual(device, 4)
        self.assertEqual(sample_rate, 48000)
        self.assertEqual(name, "USB Headset")

    def test_input_device_without_default_uses_default_input_query(self):
        class FakeDefault:
            device = (-1, -1)
        class FakeSoundDevice:
            default = FakeDefault()
            @staticmethod
            def query_devices(**kwargs):
                assert kwargs == {"kind": "input"}
                return {"name": "Built-in Microphone", "max_input_channels": 1, "default_samplerate": 44100.0}
        device, sample_rate, name = resolve_input_device_config(FakeSoundDevice)
        self.assertIsNone(device)
        self.assertEqual(sample_rate, 44100)
        self.assertEqual(name, "Built-in Microphone")

    def test_model_archive_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive_path = root / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.txt", "unsafe")
            from actions.offline_speech import _safe_extract
            with self.assertRaises(RuntimeError):
                _safe_extract(archive_path, root / "extract")
            self.assertFalse((root / "escape.txt").exists())


if __name__ == "__main__":
    unittest.main()
