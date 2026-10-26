"""환경변수 기반 설정."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Config:
    notion_token: str = _env("NOTION_TOKEN")
    meetings_db: str = _env("NOTION_MEETINGS_DB")
    tasks_db: str = _env("NOTION_TASKS_DB")
    schedule_db: str = _env("NOTION_SCHEDULE_DB")
    crm_db: str = _env("NOTION_CRM_DB")
    reports_db: str = _env("NOTION_REPORTS_DB")
    decisions_db: str = _env("NOTION_DECISIONS_DB")

    claude_model: str = _env("CLAUDE_MODEL", "claude-opus-5-5")
    timezone: str = _env("TIMEZONE", "Asia/Seoul")

    stt_backend: str = _env("STT_BACKEND", "local")
    whisper_model: str = _env("WHISPER_MODEL", "large-v3")
    openai_api_key: str = _env("OPENAI_API_KEY")

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            env_names = {
                "notion_token": "NOTION_TOKEN",
                "meetings_db": "NOTION_MEETINGS_DB",
                "tasks_db": "NOTION_TASKS_DB",
                "schedule_db": "NOTION_SCHEDULE_DB",
                "crm_db": "NOTION_CRM_DB",
                "reports_db": "NOTION_REPORTS_DB",
                "decisions_db": "NOTION_DECISIONS_DB",
            }
            raise SystemExit(
                "다음 환경변수가 필요합니다: "
                + ", ".join(env_names.get(n, n.upper()) for n in missing)
            )


CONFIG = Config()
