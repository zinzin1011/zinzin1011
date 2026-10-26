"""음성 파일 → 텍스트 (STT).

- local : faster-whisper 로 내 컴퓨터에서 전사 (무료, 한국어 품질 좋음, GPU 있으면 빠름)
- openai: OpenAI 전사 API (파일당 25MB 제한)
"""
from pathlib import Path

import httpx

from .config import CONFIG

OPENAI_LIMIT_BYTES = 25 * 1024 * 1024


def _fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _transcribe_local(path: Path) -> str:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise SystemExit("faster-whisper 가 없습니다: pip install faster-whisper") from e

    model = WhisperModel(CONFIG.whisper_model, device="auto", compute_type="auto")
    segments, _info = model.transcribe(
        str(path), language="ko", vad_filter=True, beam_size=5
    )
    return "\n".join(f"[{_fmt_ts(seg.start)}] {seg.text.strip()}" for seg in segments)


def _transcribe_openai(path: Path) -> str:
    if not CONFIG.openai_api_key:
        raise SystemExit("STT_BACKEND=openai 에는 OPENAI_API_KEY 가 필요합니다.")
    if path.stat().st_size > OPENAI_LIMIT_BYTES:
        raise SystemExit(
            "OpenAI 전사 API는 25MB 까지만 받습니다. "
            "ffmpeg 로 압축(예: -ac 1 -b:a 32k)하거나 STT_BACKEND=local 을 쓰세요."
        )
    with path.open("rb") as f:
        resp = httpx.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {CONFIG.openai_api_key}"},
            data={"model": "whisper-1", "language": "ko", "response_format": "text"},
            files={"file": (path.name, f)},
            timeout=600,
        )
    resp.raise_for_status()
    return resp.text.strip()


def transcribe(path: str | Path) -> str:
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"파일이 없습니다: {path}")
    if CONFIG.stt_backend == "openai":
        return _transcribe_openai(path)
    return _transcribe_local(path)
