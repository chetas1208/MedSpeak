from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class AudioProcessingError(Exception):
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


class AudioTooLongError(AudioProcessingError):
    def __init__(self, duration_seconds: float, limit_seconds: int) -> None:
        super().__init__(
            f"The recording is {duration_seconds:.1f} seconds long. The current limit is {limit_seconds} seconds.",
            status_code=400,
        )


@dataclass
class NormalizedAudio:
    wav_bytes: bytes
    audio_hash: str
    duration_seconds: float


def is_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _guess_suffix(content_type: Optional[str], filename: Optional[str] = None) -> str:
    if filename and "." in filename:
        return f".{filename.rsplit('.', 1)[-1]}"

    mapping = {
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/mp4": ".m4a",
        "audio/aac": ".aac",
    }
    return mapping.get((content_type or "").split(";")[0].strip().lower(), ".bin")


def _measure_wav_duration(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        frame_count = wav_file.getnframes()
        sample_rate = wav_file.getframerate()
        if sample_rate <= 0:
            raise AudioProcessingError("Converted WAV file has an invalid sample rate.")
        return frame_count / float(sample_rate)


def normalize_audio_bytes(
    *,
    audio_bytes: bytes,
    content_type: Optional[str],
    filename: Optional[str],
    max_audio_seconds: int,
) -> NormalizedAudio:
    if not is_ffmpeg_available():
        raise AudioProcessingError("ffmpeg is not installed or not on PATH.")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / f"input{_guess_suffix(content_type, filename)}"
        output_path = temp_path / "output.wav"
        input_path.write_bytes(audio_bytes)

        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(input_path),
                "-ac",
                "1",
                "-ar",
                "16000",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not output_path.exists():
            raise AudioProcessingError(result.stderr.strip() or "ffmpeg failed to normalize audio.")

        wav_bytes = output_path.read_bytes()

    duration_seconds = _measure_wav_duration(wav_bytes)
    if duration_seconds > max_audio_seconds:
        raise AudioTooLongError(duration_seconds=duration_seconds, limit_seconds=max_audio_seconds)

    return NormalizedAudio(
        wav_bytes=wav_bytes,
        audio_hash=hashlib.sha256(wav_bytes).hexdigest(),
        duration_seconds=duration_seconds,
    )
