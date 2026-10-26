"""Mac 마이크 녹음 시작/종료 (ffmpeg + avfoundation).

녹음 파일은 RECORD_DIR(구글 드라이브 동기화 폴더 추천)에 저장되므로
저장되는 순간 드라이브에 자동 업로드됩니다.
"""
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

STATE = Path.home() / ".meeting_bot" / "recording.json"


def _record_dir() -> Path:
    d = Path(os.environ.get("RECORD_DIR", "~/Recordings/meetings")).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _load() -> dict | None:
    if not STATE.exists():
        return None
    state = json.loads(STATE.read_text())
    return state if _alive(state["pid"]) else None


def list_devices() -> str:
    """녹음 장치 목록 (RECORD_DEVICE 고를 때 사용)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                       capture_output=True, text=True)
    return "\n".join(l for l in r.stderr.splitlines() if "AVFoundation" in l)


def start(name: str = "회의") -> dict:
    if sys.platform != "darwin":
        raise SystemExit("녹음 기능은 macOS 전용입니다.")
    if state := _load():
        raise SystemExit(f"이미 녹음 중입니다: {state['file']}")

    stamp = datetime.now().strftime("%y%m%d_%H%M")
    out = _record_dir() / f"{stamp}_{name}.m4a"
    log = STATE.parent / "ffmpeg.log"
    STATE.parent.mkdir(parents=True, exist_ok=True)
    device = os.environ.get("RECORD_DEVICE", ":0")  # ":0" = 기본 마이크
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "avfoundation", "-i", device,
        "-ac", "1", "-c:a", "aac", "-b:a", "64k",
        # 강제 종료돼도 그때까지 녹음분이 살아있게 조각 저장
        "-movflags", "+frag_keyframe+empty_moov",
        str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=log.open("w"), start_new_session=True)
    # 녹음 중 Mac 이 잠들지 않게
    subprocess.Popen(["caffeinate", "-i", "-w", str(proc.pid)], start_new_session=True)

    time.sleep(2)
    if proc.poll() is not None:
        raise SystemExit(
            "녹음을 시작하지 못했습니다. 마이크 권한(시스템 설정 → 개인정보 보호 → 마이크)과 "
            f"장치 번호(RECORD_DEVICE)를 확인하세요.\n{log.read_text()}"
        )
    state = {"pid": proc.pid, "file": str(out), "started": datetime.now().isoformat(timespec="seconds")}
    STATE.write_text(json.dumps(state, ensure_ascii=False))
    return state


def stop() -> dict:
    state = _load()
    if not state:
        raise SystemExit("녹음 중이 아닙니다.")
    os.kill(state["pid"], signal.SIGINT)  # ffmpeg 가 파일을 정상 마무리하도록
    for _ in range(30):
        if not _alive(state["pid"]):
            break
        time.sleep(0.5)
    else:
        os.kill(state["pid"], signal.SIGTERM)
    STATE.unlink(missing_ok=True)
    minutes = (datetime.now() - datetime.fromisoformat(state["started"])).seconds // 60
    return {**state, "minutes": minutes}


def status() -> dict | None:
    return _load()
