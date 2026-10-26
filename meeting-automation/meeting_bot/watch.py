"""녹음 폴더 감시: 새 녹음 파일이 들어오면 자동으로 STT → 노션 반영.

구글 드라이브 데스크톱 앱으로 동기화되는 공유 폴더를 지정하면,
팀원 누구든 녹음 파일을 올리기만 하면 이 컴퓨터가 처리합니다.
"""
import json
import re
import time
from datetime import date, datetime
from pathlib import Path

AUDIO_EXT = {".m4a", ".mp3", ".wav", ".aac", ".ogg", ".flac", ".webm", ".mp4", ".mov"}
STATE_FILE = ".meeting_bot_done.json"


def guess_date(path: Path) -> str:
    """파일명에서 날짜 추출 (261028, 2026-10-28, 20261028), 없으면 파일 수정일."""
    name = path.stem
    for pat, fmt in [(r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})", "%Y%m%d"), (r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)", "%y%m%d")]:
        if m := re.search(pat, name):
            try:
                return datetime.strptime("".join(m.groups()), fmt).date().isoformat()
            except ValueError:
                pass
    return date.fromtimestamp(path.stat().st_mtime).isoformat()


def _is_stable(path: Path, wait: float = 10) -> bool:
    """동기화·녹음 중인 파일은 건너뛰기 (크기가 변하지 않을 때만 처리)."""
    size = path.stat().st_size
    time.sleep(wait)
    return size > 0 and path.stat().st_size == size


def watch(folder: str, handler, interval: int = 60) -> None:
    root = Path(folder).expanduser()
    if not root.is_dir():
        raise SystemExit(f"폴더가 없습니다: {root}")
    state_path = root / STATE_FILE
    done = set(json.loads(state_path.read_text())) if state_path.exists() else set()
    print(f"👀 감시 중: {root} ({interval}초 간격, Ctrl+C 로 종료)")
    while True:
        for f in sorted(root.rglob("*")):
            key = str(f.relative_to(root))
            if f.suffix.lower() not in AUDIO_EXT or key in done or not _is_stable(f):
                continue
            print(f"\n🎙️ 새 녹음: {key}")
            try:
                handler(f, guess_date(f))
                done.add(key)
                state_path.write_text(json.dumps(sorted(done), ensure_ascii=False, indent=1))
            except Exception as e:  # 한 파일이 실패해도 감시는 계속
                print(f"⚠️ 실패 ({key}): {e} — 다음 주기에 다시 시도합니다")
        time.sleep(interval)
