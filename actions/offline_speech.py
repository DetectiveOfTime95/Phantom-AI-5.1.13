"""Local Vosk wake-word and speech recognition for Phantom-AI.

The English model is downloaded once into the user's application-data folder.
After setup, microphone recognition runs locally and does not use a cloud
speech-recognition service.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import urllib.request

from actions.secure_network import secure_urlopen
import zipfile
from collections import deque
from pathlib import Path, PurePosixPath
from typing import Any

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URLS = (
    f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip",
    f"https://huggingface.co/rhasspy/vosk-models/resolve/main/en/{MODEL_NAME}.zip",
    f"https://huggingface.co/grimso/vosk-models/resolve/main/{MODEL_NAME}.zip",
)
# SHA-256 published for the mirrored Vosk archive. The official source is also
# checked with ZIP CRC and required model-file validation.
MIRROR_SHA256 = "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498"
MAX_MODEL_ARCHIVE_BYTES = 120 * 1024 * 1024


def _app_data_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    path = root / "PhantomAI" / "speech-models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_model_ready(path: Path) -> bool:
    return (path / "am" / "final.mdl").is_file() and (path / "conf" / "mfcc.conf").is_file()


def _safe_extract(zip_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise RuntimeError(f"The speech model archive failed its integrity check: {bad_file}")
        root = destination.resolve()
        for info in archive.infolist():
            member = PurePosixPath(info.filename)
            if member.is_absolute() or ".." in member.parts:
                raise RuntimeError("The speech model archive contains an unsafe path.")
            target = (destination / Path(*member.parts)).resolve()
            if root not in target.parents and target != root:
                raise RuntimeError("The speech model archive contains an unsafe path.")
        archive.extractall(destination)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_model(progress_callback=None) -> Path:
    root = _app_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    model_dir = root / MODEL_NAME
    if _is_model_ready(model_dir):
        return model_dir

    archive_path = root / f"{MODEL_NAME}.zip.part"
    staging = root / f".{MODEL_NAME}.extracting"
    download_errors: list[str] = []
    downloaded = False
    try:
        for model_url in MODEL_URLS:
            for attempt in range(2):
                try:
                    archive_path.unlink(missing_ok=True)
                    request = urllib.request.Request(
                        model_url,
                        headers={
                            "User-Agent": "Phantom-AI/5.1.13 local-speech-setup",
                            "Accept-Encoding": "identity",
                        },
                    )
                    with secure_urlopen(request, timeout=75) as response, archive_path.open("wb") as output:
                        total = int(response.headers.get("Content-Length") or 0)
                        received = 0
                        while True:
                            chunk = response.read(1024 * 1024)
                            if not chunk:
                                break
                            received += len(chunk)
                            if received > MAX_MODEL_ARCHIVE_BYTES:
                                raise RuntimeError("Speech model download exceeded the 120 MB safety limit.")
                            output.write(chunk)
                            if progress_callback:
                                progress_callback(received, total)
                    if not zipfile.is_zipfile(archive_path):
                        raise RuntimeError("The downloaded speech model is not a valid ZIP archive.")
                    if "huggingface.co/rhasspy/" in model_url:
                        actual_hash = _sha256(archive_path)
                        if actual_hash.lower() != MIRROR_SHA256:
                            raise RuntimeError("The mirrored Vosk model failed its SHA-256 integrity check.")
                    downloaded = True
                    break
                except Exception as exc:
                    download_errors.append(
                        f"{model_url} (attempt {attempt + 1}/2): {type(exc).__name__}: {exc}"
                    )
                    archive_path.unlink(missing_ok=True)
            if downloaded:
                break

        if not downloaded:
            details = " | ".join(download_errors[-6:])
            raise RuntimeError(
                "The one-time offline speech model download failed. Check that Phantom-AI is allowed "
                "to access the Vosk and Hugging Face model hosts over HTTPS (TCP 443), then toggle "
                "VOICE OFF and ON to retry. No cloud speech recognition is used. Details: " + details
            )

        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        _safe_extract(archive_path, staging)
        extracted = staging / MODEL_NAME
        if not _is_model_ready(extracted):
            raise RuntimeError("The downloaded speech model is missing required model files.")
        if model_dir.exists():
            shutil.rmtree(model_dir, ignore_errors=True)
        extracted.replace(model_dir)
        return model_dir
    finally:
        archive_path.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)


def resolve_input_device_config(sounddevice_module):
    """Return (device id or None, native sample rate, device name).

    Windows microphones commonly run at 44.1 or 48 kHz. Forcing 16 kHz can
    produce PortAudio 'invalid sample rate' errors, so Vosk receives the
    selected microphone's native rate instead.
    """
    try:
        default_devices = sounddevice_module.default.device
        input_device = default_devices[0] if default_devices is not None else None
    except Exception:
        input_device = None

    try:
        if input_device is not None and int(input_device) >= 0:
            device_info = sounddevice_module.query_devices(int(input_device), "input")
            selected_device = int(input_device)
        else:
            selected_device = None
            device_info = sounddevice_module.query_devices(kind="input")
    except Exception as exc:
        raise RuntimeError(
            "No usable default microphone was found. In Windows, open Settings > System > Sound > Input, "
            "select a microphone, and allow desktop apps to access it. " + str(exc)
        ) from exc

    try:
        channels = int(device_info.get("max_input_channels", 1))
        sample_rate = int(round(float(device_info.get("default_samplerate") or 0)))
    except Exception as exc:
        raise RuntimeError("Windows did not report a valid microphone sample rate.") from exc
    if channels < 1:
        raise RuntimeError("The selected audio device has no microphone input channels.")
    if not 8000 <= sample_rate <= 96000:
        raise RuntimeError(f"The selected microphone reported an unsupported sample rate: {sample_rate} Hz.")
    return selected_device, sample_rate, str(device_info.get("name") or "Default microphone")


class OfflineSpeechEngine:
    def __init__(self):
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream = None
        self._recognizer = None
        self._model = None
        self._events: deque[dict[str, Any]] = deque(maxlen=40)
        self._next_event_id = 1
        self._state: dict[str, Any] = {
            "provider": "vosk-local",
            "phase": "stopped",
            "running": False,
            "ready": False,
            "modelReady": False,
            "modelName": MODEL_NAME,
            "downloadPercent": 0,
            "error": None,
            "warning": None,
            "requiresInternet": False,
            "offlineAfterModelDownload": True,
            "paused": False,
            "inputDevice": None,
            "sampleRate": None,
        }

    def _update(self, **changes):
        with self._lock:
            self._state.update(changes)

    def start(self) -> dict[str, Any]:
        previous = self._thread
        if previous and previous.is_alive() and self._stop_event.is_set():
            previous.join(timeout=3)
        with self._lock:
            if self._thread and self._thread.is_alive():
                return dict(self._state)
            self._stop_event.clear()
            self._pause_event.clear()
            self._state.update({
                "phase": "loading-model",
                "running": False,
                "ready": False,
                "error": None,
                "warning": None,
                "downloadPercent": 0,
                "paused": False,
            })
            self._thread = threading.Thread(
                target=self._run,
                name="PhantomOfflineSpeech",
                daemon=True,
            )
            self._thread.start()
            return dict(self._state)

    def _run(self):
        stream = None
        try:
            try:
                from vosk import KaldiRecognizer, Model, SetLogLevel
                import sounddevice as sd
            except Exception as exc:
                raise RuntimeError(
                    "Offline speech components are missing. Rebuild Phantom-AI with the Vosk and sounddevice dependencies."
                ) from exc

            SetLogLevel(-1)
            input_device, sample_rate, device_name = resolve_input_device_config(sd)
            self._update(inputDevice=device_name, sampleRate=sample_rate)

            def on_download(received: int, total: int):
                percent = int(received * 100 / total) if total else 0
                self._update(phase="downloading-model", downloadPercent=min(100, percent))

            model_path = ensure_model(on_download)
            self._update(phase="loading-model", modelReady=True, downloadPercent=100)
            if self._stop_event.is_set():
                self._update(phase="stopped", running=False, ready=False)
                return

            model = Model(str(model_path))
            recognizer = KaldiRecognizer(model, sample_rate)
            recognizer.SetWords(False)
            self._model = model
            self._recognizer = recognizer

            def audio_callback(indata, frames, timing, status):
                if self._stop_event.is_set() or self._pause_event.is_set():
                    return
                if status:
                    self._update(warning=str(status))
                try:
                    if recognizer.AcceptWaveform(bytes(indata)):
                        payload = json.loads(recognizer.Result() or "{}")
                        text = str(payload.get("text") or "").strip()
                        if text:
                            self._push_event(text)
                except Exception as exc:
                    self._update(error=f"Local speech recognition failed: {exc}", phase="error", ready=False, running=False)
                    self._stop_event.set()

            stream = sd.RawInputStream(
                device=input_device,
                samplerate=sample_rate,
                blocksize=0,
                dtype="int16",
                channels=1,
                callback=audio_callback,
            )
            stream.start()
            self._stream = stream
            self._update(
                phase="listening", running=True, ready=True, modelReady=True, error=None,
                inputDevice=device_name, sampleRate=sample_rate,
            )
            while not self._stop_event.wait(0.2):
                pass
        except Exception as exc:
            self._update(
                phase="error",
                running=False,
                ready=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
            self._stream = None
            self._recognizer = None
            self._model = None
            with self._lock:
                if self._state.get("phase") != "error":
                    self._state.update(phase="stopped", running=False, ready=False)

    def _push_event(self, text: str):
        transcript = " ".join(str(text or "").split()).strip()
        if not transcript:
            return
        with self._lock:
            if self._events and self._events[-1].get("text") == transcript:
                if time.time() - self._events[-1].get("time", 0) < 1.2:
                    return
            self._events.append({"id": self._next_event_id, "text": transcript, "time": time.time()})
            self._next_event_id += 1

    def pause(self) -> dict[str, Any]:
        self._pause_event.set()
        self._update(paused=True)
        return self.status(consume_events=False)

    def resume(self) -> dict[str, Any]:
        self._pause_event.clear()
        self._update(paused=False)
        return self.status(consume_events=False)

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        self._pause_event.clear()
        with self._lock:
            active = bool(self._thread and self._thread.is_alive())
            if self._state.get("phase") != "error":
                self._state.update(phase="stopping" if active else "stopped", running=False, ready=False)
            return dict(self._state)

    def status(self, consume_events: bool = True) -> dict[str, Any]:
        with self._lock:
            result = dict(self._state)
            if consume_events:
                result["events"] = list(self._events)
                self._events.clear()
            else:
                result["events"] = []
            return result


engine = OfflineSpeechEngine()
