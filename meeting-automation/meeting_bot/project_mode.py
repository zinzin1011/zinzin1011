"""기존 팀 프로젝트 노션(회의록 · 의사결정 기록 · 프로젝트 일정 DB)에 맞춘 회의 처리.

팀원 이름·회의 유형·분야 같은 선택지는 코드에 적지 않고, 실행할 때마다
노션 DB의 옵션을 읽어 와 Claude 가 그 안에서만 고르게 합니다.
(그래서 팀 정보가 저장소에 남지 않고, 노션에서 옵션을 바꾸면 자동 반영됩니다.)
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from . import notion as nb
from .config import CONFIG, load_glossary
from .notion import Notion

# 회의록 DB 속성
M_TITLE, M_DATE, M_TYPE, M_ATTEND, M_AUTHOR = "회의명", "일시", "유형", "참석자", "작성자"
M_ACTIONS, M_DECISIONS, M_NEXT = "Action Items", "핵심 결정", "다음 회의"
# 의사결정 기록 DB 속성
D_TITLE, D_CONTENT, D_BACKGROUND, D_OPTIONS = "결정 사항", "결정 내용", "배경", "검토한 선택지"
D_REASON, D_DATE, D_AREA, D_PEOPLE, D_STATUS = "근거", "결정일", "분야", "결정 참여", "상태"
# 프로젝트 일정 DB 속성
S_TITLE, S_DATE, S_KIND, S_OWNER, S_MEMO, S_STATUS = "일정", "날짜", "구분", "담당", "메모", "상태"


def _options(db: dict, prop: str) -> list[str]:
    p = db["properties"].get(prop)
    if not p:
        return []
    return [o["name"] for o in p[p["type"]].get("options", [])]


def _enum(values: list[str]) -> dict:
    return {"type": "string", "enum": values} if values else {"type": "string"}


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _schema(m_db: dict, d_db: dict | None, s_db: dict | None) -> dict:
    s = {"type": "string"}
    strs = {"type": "array", "items": s}
    people = _options(m_db, M_ATTEND)
    owners = _options(s_db, S_OWNER) if s_db else people
    return _obj({
        "topic": s,
        "meeting_type": _enum(_options(m_db, M_TYPE)),
        "attendees": {"type": "array", "items": _enum(people)},
        "agenda": {"type": "array", "items": _obj({"title": s, "discussion": strs})},
        "decisions": {"type": "array", "items": _obj({
            "title": s,
            "content": s,
            "background": s,
            "options_considered": s,
            "rationale": s,
            "area": _enum(_options(d_db, D_AREA)) if d_db else s,
            "participants": {"type": "array", "items": _enum(_options(d_db, D_PEOPLE) if d_db else people)},
            "important": {"type": "boolean"},
        })},
        "action_items": {"type": "array", "items": _obj({
            "task": s,
            "owner": _nullable(_enum(owners)),
            "due_date": _nullable(s),
        })},
        "next_meeting": _nullable(_obj({"date": s, "time": _nullable(s), "agenda": strs})),
        "key_events": {"type": "array", "items": _obj({
            "title": s,
            "date": s,
            "end_date": _nullable(s),
            "kind": _enum(_options(s_db, S_KIND)) if s_db else s,
            "owners": {"type": "array", "items": _enum(owners)},
            "memo": s,
        })},
        "open_questions": strs,
    })


SYSTEM = """당신은 팀 프로젝트의 회의록 담당자입니다. STT 전사본은 오탈자·화자 누락이 있으니 문맥으로 보정하세요.

규칙:
- 전사본에 없는 사실은 만들지 마세요. 불확실하면 빈 값/null.
- topic: 회의 주제를 15자 내외로 (회의명 'YYMMDD_유형_주제' 의 주제 부분).
- 사람 이름은 반드시 주어진 선택지 중에서만 고르세요. 별명·성만 부른 경우 문맥(역할 등)으로 매칭하고, 확실하지 않으면 넣지 마세요.
- agenda: 안건별로 논의된 내용을 bullet 로.
- decisions: '하기로 했다/확정' 류만. 논의만 된 건 open_questions.
  important=true 는 기술 스택, 범위, 비교 기준, 일정 변경처럼 나중에 근거를 찾아볼 결정.
- action_items: 담당자와 기한(YYYY-MM-DD)을 함께. "다음 주 수요일" 같은 상대 날짜는 회의 날짜 기준으로 계산.
- next_meeting: 다음 회의 날짜가 언급됐을 때만.
- key_events: 새로 정해졌거나 바뀐 마감·마일스톤·멘토링·작업 기간 등 프로젝트 일정에 올릴 것만. 다음 회의는 넣지 마세요.
"""


def _date(day: str | None, time_: str | None = None) -> dict:
    if not day:
        return {"date": None}
    try:
        datetime.fromisoformat(day)
    except ValueError:
        return {"date": None}
    if time_:
        try:
            datetime.strptime(time_, "%H:%M")
            return {"date": {"start": f"{day}T{time_}:00", "time_zone": CONFIG.timezone}}
        except ValueError:
            pass
    return {"date": {"start": day}}


def _select(name: str | None, allowed: list[str]) -> dict | None:
    return {"select": {"name": name}} if name and name in allowed else None


def _multi(names: list[str], allowed: list[str]) -> dict:
    return {"multi_select": [{"name": n} for n in dict.fromkeys(names) if n in allowed]}


def _action_line(t: dict) -> str:
    return " / ".join([t["task"], t["owner"] or "담당 미정", t["due_date"] or "기한 미정"])


def _body(a: dict, transcript: str, decision_links: list[tuple[str, str]]) -> list[dict]:
    b = [nb.heading("안건")]
    b += [nb.numbered(x["title"]) for x in a["agenda"]] or [nb.para("기록 없음")]

    b.append(nb.heading("논의 내용"))
    for i, x in enumerate(a["agenda"], 1):
        b.append(nb.heading(f"안건 {i}. {x['title']}", 3))
        b += [nb.bullet(d) for d in x["discussion"]]

    b.append(nb.heading("결정 사항"))
    b += [nb.bullet(f"{d['title']}: {d['content']}") for d in a["decisions"]] or [nb.para("없음")]
    if decision_links:
        b.append(nb.callout("의사결정 기록 DB에 등록됨: " + ", ".join(f"{t} ({u})" for t, u in decision_links), "📌"))

    b.append(nb.heading("Action Items"))
    b += [nb.todo(_action_line(t)) for t in a["action_items"]] or [nb.para("없음")]

    b.append(nb.heading("다음 회의 안건"))
    nxt = a["next_meeting"]
    if nxt:
        b.append(nb.para(f"일시: {nxt['date']} {nxt['time'] or ''}".strip()))
        b += [nb.bullet(x) for x in nxt["agenda"]]
    b += [nb.bullet(f"(미결) {q}") for q in a["open_questions"]]

    chunks = [transcript[i:i + 1900] for i in range(0, len(transcript), 1900)]
    b += [nb.divider(), nb.toggle("🎙️ 전체 녹취 (자동 STT)", [nb.para(c) for c in chunks[:100]])]
    return b


def _schedule_exists(n: Notion, s_db_id: str, day: str, title: str) -> bool:
    for p in n.query(s_db_id, {"property": S_DATE, "date": {"equals": day}}):
        existing = nb.prop_title(p).replace(" ", "")
        new = title.replace(" ", "")
        if existing and (existing in new or new in existing):
            return True
    return False


def _load_dbs(n: Notion) -> tuple[dict, dict | None, dict | None]:
    CONFIG.require("notion_token", "meetings_db")
    m_db = n._req("GET", f"/databases/{CONFIG.meetings_db}")
    d_db = n._req("GET", f"/databases/{CONFIG.decisions_db}") if CONFIG.decisions_db else None
    s_db = n._req("GET", f"/databases/{CONFIG.schedule_db}") if CONFIG.schedule_db else None
    return m_db, d_db, s_db


def _rules() -> str:
    terms = load_glossary()
    if not terms:
        return SYSTEM
    return SYSTEM + (
        "\n용어집: 녹취에서 아래 용어가 비슷한 발음으로 잘못 받아써졌으면 이 표기로 고쳐서 쓰세요.\n- "
        + "\n- ".join(terms) + "\n"
    )


def analysis_spec() -> dict:
    """Claude Code 가 직접 분석할 때 쓰는 규칙 + JSON 스키마 (노션 선택지·용어집 반영)."""
    return {"rules": _rules(), "schema": _schema(*_load_dbs(Notion()))}


def process_project_meeting(transcript: str, meeting_date: str | None = None, meeting_time: str | None = None,
                            author: str | None = None, dry_run: bool = False,
                            analysis: dict | None = None) -> dict:
    """analysis 를 주면 (Claude Code 가 이미 분석한 경우) Claude API 를 부르지 않습니다."""
    n = Notion()
    meeting_date = meeting_date or datetime.now(ZoneInfo(CONFIG.timezone)).date().isoformat()
    m_db, d_db, s_db = _load_dbs(n)

    a = analysis
    if a is None:
        from .llm import ask_json
        print("🧠 Claude 로 회의 분석 중...")
        a = ask_json(_rules(), f"회의 날짜: {meeting_date}\n\n<transcript>\n{transcript}\n</transcript>",
                     _schema(m_db, d_db, s_db), effort="high")
    if dry_run:
        return {"analysis": a}

    yymmdd = meeting_date[2:].replace("-", "")
    title = f"{yymmdd}_{a['meeting_type'].replace(' ', '')}_{a['topic']}"

    # 1) 중요한 결정 → 의사결정 기록 DB (배경·선택지·근거까지)
    decision_links = []
    if d_db:
        for d in a["decisions"]:
            if not d["important"]:
                continue
            props = {
                D_TITLE: {"title": nb.rich(d["title"])},
                D_CONTENT: {"rich_text": nb.rich(d["content"])},
                D_BACKGROUND: {"rich_text": nb.rich(d["background"])},
                D_OPTIONS: {"rich_text": nb.rich(d["options_considered"])},
                D_REASON: {"rich_text": nb.rich(d["rationale"])},
                D_DATE: _date(meeting_date),
                D_PEOPLE: _multi(d["participants"], _options(d_db, D_PEOPLE)),
                D_STATUS: {"status": {"name": "확정"}},
            }
            if area := _select(d["area"], _options(d_db, D_AREA)):
                props[D_AREA] = area
            page = n.create_page(d_db["id"], props, [nb.para(f"출처 회의: {title}")])
            decision_links.append((d["title"], nb.page_url(page)))
        print(f"⚖️ 의사결정 기록 {len(decision_links)}건 등록")

    # 2) 회의록 페이지 (팀 양식: 안건 / 논의 내용 / 결정 사항 / Action Items / 다음 회의 안건)
    nxt = a["next_meeting"]
    props = {
        M_TITLE: {"title": nb.rich(title)},
        M_DATE: _date(meeting_date, meeting_time),
        M_ATTEND: _multi(a["attendees"], _options(m_db, M_ATTEND)),
        M_ACTIONS: {"rich_text": nb.rich("\n".join(_action_line(t) for t in a["action_items"]))},
        M_DECISIONS: {"rich_text": nb.rich("\n".join(d["title"] for d in a["decisions"]))},
        M_NEXT: _date(nxt["date"], nxt["time"]) if nxt else {"date": None},
    }
    if t := _select(a["meeting_type"], _options(m_db, M_TYPE)):
        props[M_TYPE] = t
    if au := _select(author, _options(m_db, M_AUTHOR)):
        props[M_AUTHOR] = au
    meeting = n.create_page(m_db["id"], props, _body(a, transcript, decision_links))
    rest = [transcript[i:i + 1900] for i in range(0, len(transcript), 1900)][100:]
    if rest:
        toggle_id = [b for b in n.children(meeting["id"]) if b["type"] == "toggle"][-1]["id"]
        n.append_blocks(toggle_id, [nb.para(c) for c in rest])
    print(f"🗣️ 회의록 생성: {nb.page_url(meeting)}")

    # 3) 다음 회의 + 새 일정 → 프로젝트 일정 DB (같은 날짜·제목이 있으면 건너뜀)
    added = 0
    if s_db:
        kinds = _options(s_db, S_KIND)
        events = list(a["key_events"])
        if nxt:
            kind = "멘토링" if "멘토" in a["meeting_type"] and "멘토링" in kinds else "회의"
            events.append({"title": f"다음 {a['meeting_type']}", "date": nxt["date"], "end_date": None,
                           "kind": kind, "owners": ["전원"], "memo": ", ".join(nxt["agenda"]),
                           "time": nxt["time"]})
        for e in events:
            if _date(e["date"])["date"] is None or _schedule_exists(n, s_db["id"], e["date"], e["title"]):
                continue
            date_prop = _date(e["date"], e.get("time"))
            if e.get("end_date") and _date(e["end_date"])["date"]:
                date_prop["date"]["end"] = e["end_date"]
            sprops = {
                S_TITLE: {"title": nb.rich(e["title"])},
                S_DATE: date_prop,
                S_OWNER: _multi(e["owners"], _options(s_db, S_OWNER)),
                S_MEMO: {"rich_text": nb.rich(f"{e['memo']} (출처: {title})".strip())},
                S_STATUS: {"status": {"name": "예정"}},
            }
            if k := _select(e["kind"], kinds):
                sprops[S_KIND] = k
            n.create_page(s_db["id"], sprops)
            added += 1
        print(f"🗓️ 프로젝트 일정 {added}건 추가")

    return {"meeting": meeting, "analysis": a}
