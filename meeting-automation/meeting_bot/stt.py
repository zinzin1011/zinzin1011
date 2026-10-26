"""음성 파일 → 텍스트 (STT) + 화자 구분.

STT_BACKEND
- mlx   : mlx-whisper, Apple Silicon Mac 의 GPU 사용 (Mac 추천, 무료)
- local : faster-whisper, CPU/NVIDIA GPU (무료)
- openai: OpenAI 전사 API (유료, 파일당 25MB 제한)

화자 구분(diarize=True)은 pyannote 로 내 컴퓨터에서 처리합니다 (무료, HF_TOKEN 필요).
결과 예: [00:01:02] [화자1] 그럼 수집기는 금요일까지 하죠
"""
import os
import subprocess
import tempfile
from pathlib import Path

import httpx

from .config import CONFIG

OPENAI_LIMIT_BYTES = 25 * 1024 * 1024
MLX_MODEL = os.environ.get("MLX_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")
DIARIZE_MODEL = os.environ.get("DIARIZE_MODEL", "pyannote/speaker-diarization-3.1")


def _fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# 각 백엔드는 [(start, end, text), ...] 를 돌려줌 -------------------------------
def _segments_mlx(path: Path) -> list[tuple[float, float, str]]:
    try:
        import mlx_whisper
    except ImportError as e:
        raise SystemExit("mlx-whisper 가 없습니다: pip install mlx-whisper (Apple Silicon Mac 전용)") from e
    result = mlx_whisper.transcribe(str(path), path_or_hf_repo=MLX_MODEL, language="ko")
    return [(s["start"], s["end"], s["text"].strip()) for s in result["segments"]]


def _segments_local(path: Path) -> list[tuple[float, float, str]]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise SystemExit("faster-whisper 가 없습니다: pip install faster-whisper") from e
    model = WhisperModel(CONFIG.whisper_model, device="auto", compute_type="auto")
    segments, _info = model.transcribe(str(path), language="ko", vad_filter=True, beam_size=5)
    return [(s.start, s.end, s.text.strip()) for s in segments]


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


# 화자 구분 -------------------------------------------------------------------
def _diarize(path: Path) -> list[tuple[float, float, str]]:
    """[(start, end, speaker_label), ...]"""
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "화자 구분에는 HF_TOKEN 이 필요합니다 (무료). README 의 '화자 구분 준비' 를 보세요."
        )
    try:
        import torch
        from pyannote.audio import Pipeline
    except ImportError as e:
        raise SystemExit("pyannote.audio 가 없습니다: pip install pyannote.audio") from e

    try:
        pipeline = Pipeline.from_pretrained(DIARIZE_MODEL, token=token)
    except TypeError:  # pyannote.audio 3.x
        pipeline = Pipeline.from_pretrained(DIARIZE_MODEL, use_auth_token=token)
    if pipeline is None:
        raise SystemExit(f"{DIARIZE_MODEL} 모델 이용 약관에 동의했는지 확인하세요 (huggingface.co).")
    if torch.backends.mps.is_available():
        pipeline.to(torch.device("mps"))
    elif torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))

    # m4a 등은 바로 못 읽는 경우가 있어 16kHz 모노 wav 로 변환 후 사용
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", "16000", str(wav)],
                       check=True)
        output = pipeline(str(wav))
    annotation = getattr(output, "speaker_diarization", output)  # pyannote 4.x / 3.x

    labels: dict[str, str] = {}
    turns = []
    for turn, _, spk in annotation.itertracks(yield_label=True):
        labels.setdefault(spk, f"화자{len(labels) + 1}")
        turns.append((turn.start, turn.end, labels[spk]))
    return turns


def _assign_speakers(segments, turns) -> list[tuple[float, float, str, str]]:
    """각 받아쓰기 구간에 가장 많이 겹치는 화자를 붙임."""
    out = []
    for start, end, text in segments:
        best, best_overlap = "화자?", 0.0
        for t_start, t_end, spk in turns:
            overlap = min(end, t_end) - max(start, t_start)
            if overlap > best_overlap:
                best, best_overlap = spk, overlap
        out.append((start, end, best, text))
    return out


def _format(rows: list[tuple[float, float, str, str]]) -> str:
    """같은 화자가 연달아 말하면 한 줄로 합침."""
    lines, cur = [], None
    for start, _end, spk, text in rows:
        if not text:
            continue
        if cur and cur[1] == spk:
            cur[2].append(text)
        else:
            if cur:
                lines.append(cur)
            cur = [start, spk, [text]]
    if cur:
        lines.append(cur)
    return "\n".join(
        f"[{_fmt_ts(s)}]" + (f" [{spk}]" if spk else "") + " " + " ".join(texts) for s, spk, texts in lines
    )


def transcribe(path: str | Path, diarize: bool | None = None) -> str:
    """diarize=None 이면 HF_TOKEN 이 설정돼 있을 때만 화자 구분."""
    if diarize is None:
        diarize = bool(os.environ.get("HF_TOKEN", "").strip())
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"파일이 없습니다: {path}")
    if CONFIG.stt_backend == "openai":
        if diarize:
            print("⚠️ openai 백엔드는 화자 구분을 지원하지 않아 생략합니다.")
        return _transcribe_openai(path)

    segments = _segments_mlx(path) if CONFIG.stt_backend == "mlx" else _segments_local(path)
    if diarize:
        print("🗣️ 화자 구분 중...")
        rows = _assign_speakers(segments, _diarize(path))
    else:
        rows = [(s, e, "", t) for s, e, t in segments]
    return _format(rows)
