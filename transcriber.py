"""faster-whisper wrapper for audio transcription."""

import logging
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Module-level model cache to avoid reloading on every call
_model_cache = {}


@dataclass
class Transcript:
    text: str
    language: str
    segments: list  # list of (start, end, text) tuples


def extract_audio(video_path: str, audio_path: str) -> str:
    """Extract audio from video using ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",                    # no video
        "-acodec", "pcm_s16le",   # WAV 16-bit
        "-ar", "16000",           # 16kHz for Whisper
        "-ac", "1",               # mono
        audio_path,
    ]
    log.info("Extracting audio: %s", Path(video_path).name)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")

    size = Path(audio_path).stat().st_size
    duration_est = size / (16000 * 2)  # 16kHz, 16-bit mono
    log.info("Audio extracted: %.1fs, %d bytes", duration_est, size)
    return audio_path


def _get_model(model_size: str, device: str, compute_type: str):
    """Load model with caching and progress logging."""
    cache_key = (model_size, device, compute_type)
    if cache_key in _model_cache:
        log.info("Using cached whisper model: %s", model_size)
        return _model_cache[cache_key]

    from faster_whisper import WhisperModel

    log.info(
        "Loading whisper model: %s (device=%s, compute=%s). "
        "First run will download ~500MB, please wait...",
        model_size, device, compute_type,
    )
    t0 = time.time()
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    log.info("Model loaded in %.1fs", time.time() - t0)

    _model_cache[cache_key] = model
    return model


def transcribe(
    video_path: str,
    model_size: str = "small",
    device: str = "cpu",
    compute_type: str = "int8",
) -> Transcript:
    """Transcribe video audio using faster-whisper.

    Args:
        video_path: Path to video file.
        model_size: Whisper model size (small/medium/large-v3).
        device: "cpu" or "cuda".
        compute_type: "int8" for CPU, "float16" for GPU.

    Returns:
        Transcript with full text and segments.
    """
    # Extract audio to temp WAV
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = tmp.name

    try:
        extract_audio(video_path, audio_path)

        model = _get_model(model_size, device, compute_type)

        log.info("Starting transcription: %s", Path(video_path).name)
        t0 = time.time()

        segments_iter, info = model.transcribe(
            audio_path,
            language="zh",
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
            ),
        )

        segments = []
        full_text_parts = []
        last_log_time = t0

        for seg in segments_iter:
            segments.append((seg.start, seg.end, seg.text.strip()))
            full_text_parts.append(seg.text.strip())

            # Progress log every 30 seconds
            now = time.time()
            if now - last_log_time > 30:
                log.info(
                    "  Transcribing... %d segments so far, at %.1fs of audio (elapsed: %.0fs)",
                    len(segments), seg.end, now - t0,
                )
                last_log_time = now

        elapsed = time.time() - t0
        full_text = "\n".join(full_text_parts)
        detected_lang = info.language if info.language else "zh"

        log.info(
            "Transcription done: %d segments, %d chars, language=%s, took %.1fs",
            len(segments), len(full_text), detected_lang, elapsed,
        )

        return Transcript(
            text=full_text,
            language=detected_lang,
            segments=segments,
        )

    finally:
        Path(audio_path).unlink(missing_ok=True)
