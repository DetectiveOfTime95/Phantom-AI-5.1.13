"""Microsoft Edge TTS provider used by Phantom-AI.

All network speech output goes through Microsoft's Edge speech service. No voice
API key, extra voice model, or separate account is required. The selected voice
is a refined original British male neural delivery, not an imitation of an actor.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import time
from typing import Any

from actions.speech_text import clean_for_speech

DEFAULT_VOICE = "en-GB-RyanNeural"
DEFAULT_RATE = "-7%"
DEFAULT_PITCH = "-10Hz"
_last_voice_error: str | None = None
_last_provider: str | None = None


def _settings() -> dict[str, str]:
    return {
        "voice": os.environ.get("PHANTOM_EDGE_VOICE", DEFAULT_VOICE).strip() or DEFAULT_VOICE,
        "rate": os.environ.get("PHANTOM_EDGE_RATE", DEFAULT_RATE).strip() or DEFAULT_RATE,
        "pitch": os.environ.get("PHANTOM_EDGE_PITCH", DEFAULT_PITCH).strip() or DEFAULT_PITCH,
    }


def status() -> dict[str, Any]:
    installed = importlib.util.find_spec("edge_tts") is not None
    settings = _settings()
    return {
        "provider": "microsoft-edge-tts",
        "model": settings["voice"],
        "voice": settings["voice"],
        "installed": installed,
        "ready": installed,
        "requiresInternet": True,
        "networkVoiceRequiresInternet": True,
        "loaded": installed,
        "lastError": _last_voice_error,
        "lastProvider": _last_provider,
        "persona": "original polished British male assistant delivery: calm, precise, lightly formal, measured, and lower-pitched",
        "note": "Speech output uses Microsoft Edge TTS. Wake-word recognition is handled by the local Vosk engine.",
    }


async def _generate_edge_audio(text: str, settings: dict[str, str]) -> bytes:
    import edge_tts

    communicate = edge_tts.Communicate(
        text=text,
        voice=settings["voice"],
        rate=settings["rate"],
        pitch=settings["pitch"],
    )
    chunks: list[bytes] = []
    async for item in communicate.stream():
        if item.get("type") == "audio":
            audio = item.get("data", b"")
            if audio:
                chunks.append(audio)
    audio_bytes = b"".join(chunks)
    if not audio_bytes:
        raise RuntimeError("Microsoft Edge TTS returned no audio data.")
    return audio_bytes


def synthesize_audio(text: str) -> tuple[bytes, str]:
    """Synthesize MP3 speech using Microsoft Edge TTS only."""
    global _last_voice_error, _last_provider
    payload = clean_for_speech(text)
    if not payload:
        raise ValueError("Text is required.")
    if len(payload) > 4000:
        raise ValueError("Text is too long; limit is 4000 characters.")

    if importlib.util.find_spec("edge_tts") is None:
        _last_provider = None
        _last_voice_error = "The edge-tts module is missing from the bundled backend. Rebuild Phantom-AI with its Edge TTS dependency."
        raise RuntimeError(_last_voice_error)

    settings = _settings()
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            audio_bytes = asyncio.run(
                asyncio.wait_for(_generate_edge_audio(payload, settings), timeout=22)
            )
            _last_provider = "microsoft-edge-tts"
            _last_voice_error = None
            return audio_bytes, "audio/mpeg"
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.5)

    detail = f"{type(last_error).__name__}: {last_error}"
    _last_provider = None
    _last_voice_error = detail
    raise RuntimeError(
        "Microsoft Edge TTS could not reach the speech service. Check internet access and "
        "firewall/proxy permission for speech.platform.bing.com over HTTPS/WebSocket (TCP 443). "
        f"Details: {detail}"
    ) from last_error
