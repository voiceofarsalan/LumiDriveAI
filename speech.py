import io
import os
from typing import Optional, Tuple

from assistant import client

STT_MODEL = os.getenv("STT_MODEL", "gpt-4o-mini-transcribe")
TTS_MODEL = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.getenv("TTS_VOICE", "alloy")
TTS_FORMAT = os.getenv("TTS_FORMAT", "mp3")


def transcribe_audio(
    audio_bytes: bytes,
    filename: str = "audio.wav",
    language: Optional[str] = None,
) -> dict:
    """
    Send raw audio bytes to the OpenAI transcription model.
    Returns the full response dict including text + segments if available.
    """
    file_obj = io.BytesIO(audio_bytes)
    file_obj.name = filename

    response = client.audio.transcriptions.create(
        model=STT_MODEL,
        file=file_obj,
        **({"language": language} if language else {}),
    )
    # response is an OpenAI object; expose a simple dict
    return {
        "text": getattr(response, "text", None),
        "language": getattr(response, "language", language),
        "duration": getattr(response, "duration", None),
        "segments": getattr(response, "segments", None),
    }


def synthesize_speech(
    text: str,
    voice: Optional[str] = None,
    audio_format: Optional[str] = None,
) -> Tuple[bytes, str]:
    """
    Generate speech audio for the provided text.
    Returns (audio_bytes, content_type).
    """
    voice = voice or TTS_VOICE
    audio_format = audio_format or TTS_FORMAT

    response = client.audio.speech.create(
        model=TTS_MODEL,
        voice=voice,
        input=text,
        response_format=audio_format,
    )
    audio_bytes = b"".join(response.iter_bytes())

    content_type = {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "pcm16": "audio/L16",
        "flac": "audio/flac",
        "ogg": "audio/ogg",
    }.get(audio_format.lower(), "application/octet-stream")

    return audio_bytes, content_type

