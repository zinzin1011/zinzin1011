"""회의 1건 처리: 전사본 → 분석 → 회의록·할 일·일정·CRM 자동 반영."""
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import notion as nb
from .config import CONFIG
from .llm import analyze_meeting
from .notion import Notion


def _date_prop(day: str | None, time_: str | None = None) -> dict:
    if not day:
        return {"date": None}
    if time_:
        return {"date": {"start": f"{day}T{time_}:00", "time_zone": CONFIG.timezone}}
    return {"date": {"start": day}}


def _valid_date(s: str | None) -> str | None:
    try:
        return date.fromisoformat(s).isoformat() if s else None
    except ValueError:
        return None


def _valid_time(s: str | None) -> str | None:
    try:
        return datetime.strptime(s, "%H:%M").strftime("%H:%M") if s else None
    except ValueError:
        return None


def _multi(names: list[str]) -> dict:
    # multi_select 옵션명에 쉼표 불가
    return {"multi_select": [{"name": n.replace(",", " ")[:100]} for n in names if n]}


def _meeting_blocks(a: dict, transcript: str) -> list[dict]:
    b = [nb.heading("📝 요약")]
    b += [nb.bullet(s) for s in a["summary"]]
    if a["summary_en"]:
        b.append(nb.toggle("🌐 English summary", [nb.bullet(s) for s in a["summary_en"]]))

    b.append(nb.heading("✅ 결정사항"))
    b += [nb.bullet(f"{d['decision']} — {d['rationale']}" if d["rationale"] else d["decision"])
          for d in a["decisions"]] or [nb.para("없음")]

    b.append(nb.heading("🎯 액션아이템"))
    for t in a["action_items"]:
        meta = " · ".join(x for x in [t["owner"] and f"@{t['owner']}", t["due_date"] and f"~{t['due_date']}"] if x)
        b.append(nb.todo(f"{t['task']}" + (f"  ({meta})" if meta else "")))
    if not a["action_items"]:
        b.append(nb.para("없음"))

    if a["key_events"]:
        b.append(nb.heading("📅 핵심 일정"))
        b += [nb.bullet(f"{e['date']} {e['time'] or ''} [{e['kind']}] {e['title']}".replace("  ", " "))
              for e in a["key_events"]]
    if a["policy_changes"]:
        b.append(nb.heading("📌 정책·프로세스 변경"))
        b += [nb.bullet(f"{p['topic']}: {p['change']}") for p in a["policy_changes"]]
    if a["ideas"]:
        b.append(nb.heading("💡 아이디어"))
        b += [nb.bullet(i) for i in a["ideas"]]
    if a["open_questions"]:
        b.append(nb.heading("❓ 미결 사항"))
        b += [nb.bullet(q) for q in a["open_questions"]]

    # 전사본은 토글 안에 (토글 생성 시 children 은 100개까지 → 나머지는 후처리)
    chunks = _transcript_chunks(transcript)
    b += [nb.divider(), nb.toggle("🎙️ 전체 전사본 (STT)", [nb.para(c) for c in chunks[:100]])]
    return b


def _transcript_chunks(transcript: str) -> list[str]:
    return [transcript[i:i + 1900] for i in range(0, len(transcript), 1900)]


def _find_or_create_customer(n: Notion, name: str) -> str:
    hits = n.query(CONFIG.crm_db, {"property": "고객사", "title": {"contains": name}})
    if hits:
        return hits[0]["id"]
    page = n.create_page(CONFIG.crm_db, {
        "고객사": {"title": nb.rich(name)},
        "단계": {"select": {"name": "미팅중"}},
    })
    return page["id"]


def write_ics(events: list[dict], path: Path) -> None:
    """캘린더 앱(구글/아웃룩/애플)에 바로 가져올 수 있는 .ics 파일."""
    tz = ZoneInfo(CONFIG.timezone)
    stamp = datetime.now(tz).strftime("%Y%m%dT%H%M%S")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//meeting-bot//KO"]
    for i, e in enumerate(events):
        d = e["date"].replace("-", "")
        lines += ["BEGIN:VEVENT", f"UID:{stamp}-{i}@meeting-bot", f"DTSTAMP:{stamp}"]
        if e.get("time"):
            start = datetime.fromisoformat(f"{e['date']}T{e['time']}")
            end = start + timedelta(hours=1)
            lines += [f"DTSTART;TZID={CONFIG.timezone}:{start:%Y%m%dT%H%M%S}",
                      f"DTEND;TZID={CONFIG.timezone}:{end:%Y%m%dT%H%M%S}"]
        else:
            nxt = (date.fromisoformat(e["date"]) + timedelta(days=1)).strftime("%Y%m%d")
            lines += [f"DTSTART;VALUE=DATE:{d}", f"DTEND;VALUE=DATE:{nxt}"]
        summary = f"[{e['kind']}] {e['title']}".replace(",", "\\,").replace(";", "\\;")
        desc = (e.get("agenda") or "").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")
        lines += [f"SUMMARY:{summary}", f"DESCRIPTION:{desc}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")


def process_transcript(transcript: str, meeting_date: str | None = None,
                       title: str | None = None, ics_path: Path | None = None) -> dict:
    CONFIG.require("notion_token", "meetings_db", "tasks_db", "schedule_db")
    meeting_date = meeting_date or datetime.now(ZoneInfo(CONFIG.timezone)).date().isoformat()
    n = Notion()

    print("🧠 Claude 로 회의 분석 중...")
    a = analyze_meeting(transcript, meeting_date, title)
    a["title"] = title or a["title"]

    # 1) 회의록 페이지
    props = {
        "제목": {"title": nb.rich(a["title"])},
        "날짜": _date_prop(meeting_date),
        "유형": {"select": {"name": a["meeting_type"]}},
        "참석자": _multi(a["attendees"]),
        "태그": _multi(a["tags"]),
        "요약": {"rich_text": nb.rich(" / ".join(a["summary"]))},
        "결정사항": {"rich_text": nb.rich("\n".join(d["decision"] for d in a["decisions"]))},
    }
    # 3) 고객콜이면 CRM relation 연결 → 고객 페이지에 미팅 히스토리 누적
    if a["customer_name"] and CONFIG.crm_db:
        props["고객"] = {"relation": [{"id": _find_or_create_customer(n, a["customer_name"])}]}

    meeting = n.create_page(CONFIG.meetings_db, props, _meeting_blocks(a, transcript))
    rest = _transcript_chunks(transcript)[100:]
    if rest:  # 아주 긴 회의: 토글에 나머지 전사본 이어 붙이기
        toggle_id = [b for b in n.children(meeting["id"]) if b["type"] == "toggle"][-1]["id"]
        n.append_blocks(toggle_id, [nb.para(c) for c in rest])
    print(f"🗒️ 회의록 생성: {nb.page_url(meeting)}")

    # 1) 액션아이템 → 할 일 DB (담당자·마감일 자동)
    for t in a["action_items"]:
        tprops = {
            "할 일": {"title": nb.rich(t["task"])},
            "담당자명": {"rich_text": nb.rich(t["owner"] or "")},
            "마감일": _date_prop(_valid_date(t["due_date"])),
            "상태": {"select": {"name": "할 일"}},
            "우선순위": {"select": {"name": t["priority"]}},
            "회의록": {"relation": [{"id": meeting["id"]}]},
        }
        if uid := n.find_user(t["owner"]):
            tprops["담당자"] = {"people": [{"id": uid}]}
        n.create_page(CONFIG.tasks_db, tprops)
    print(f"✅ 할 일 {len(a['action_items'])}건 등록")

    # 7) 핵심 일정 + 후속 미팅 → 일정 DB (노션 캘린더에 표시) + .ics
    events = [{**e, "time": _valid_time(e["time"])} for e in a["key_events"] if _valid_date(e["date"])]
    for e in events:
        n.create_page(CONFIG.schedule_db, {
            "일정": {"title": nb.rich(e["title"])},
            "날짜": _date_prop(e["date"], e["time"]),
            "구분": {"select": {"name": e["kind"]}},
            "참석자": {"rich_text": nb.rich(", ".join(e["attendees"]))},
            "안건": {"rich_text": nb.rich(e["agenda"])},
            "회의록": {"relation": [{"id": meeting["id"]}]},
        })
    print(f"📅 핵심 일정 {len(events)}건 반영")
    if events and ics_path:
        write_ics(events, ics_path)
        print(f"📆 캘린더 파일: {ics_path}")

    return {"meeting": meeting, "analysis": a}
