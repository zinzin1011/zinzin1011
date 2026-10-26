"""회의록 활용 확장 기능 (#2, #4, #5, #6, #9, #10)."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import notion as nb
from .config import CONFIG
from .llm import ask_text
from .notion import Notion

BASE_RULES = "한국어로, 회의록에 근거한 내용만 쓰세요. 근거가 없으면 '기록 없음'이라고 하세요. 마크다운(#, -, 1.)으로 작성하세요."


def _today() -> date:
    return datetime.now(ZoneInfo(CONFIG.timezone)).date()


def meetings_between(n: Notion, start: str, end: str, keyword: str | None = None) -> list[dict]:
    filters = [
        {"property": "날짜", "date": {"on_or_after": start}},
        {"property": "날짜", "date": {"on_or_before": end}},
    ]
    if keyword:
        filters.append({"or": [
            {"property": "제목", "title": {"contains": keyword}},
            {"property": "태그", "multi_select": {"contains": keyword}},
            {"property": "참석자", "multi_select": {"contains": keyword}},
        ]})
    return n.query(CONFIG.meetings_db, {"and": filters},
                   sorts=[{"property": "날짜", "direction": "ascending"}])


def _meeting_digest(n: Notion, pages: list[dict], full: bool = False) -> str:
    out = []
    for p in pages:
        head = (f"## [{nb.prop_text(p, '날짜')}] {nb.prop_title(p)} ({nb.prop_text(p, '유형')})\n"
                f"링크: {nb.page_url(p)}\n참석자: {nb.prop_text(p, '참석자')}")
        if full:
            out.append(f"{head}\n{n.page_text(p['id'], depth=0)}")
        else:
            out.append(f"{head}\n요약: {nb.prop_text(p, '요약')}\n결정사항:\n{nb.prop_text(p, '결정사항')}")
    return "\n\n".join(out)


def _save_report(n: Notion, title: str, kind: str, md: str, start: str | None = None,
                 end: str | None = None) -> dict:
    CONFIG.require("reports_db")
    props = {"제목": {"title": nb.rich(title)}, "종류": {"select": {"name": kind}}}
    if start:
        props["기간"] = {"date": {"start": start, **({"end": end} if end and end != start else {})}}
    page = n.create_page(CONFIG.reports_db, props, nb.markdown_blocks(md))
    print(f"📄 {kind} 저장: {nb.page_url(page)}")
    return page


# #2 여러 회의록 → 결정사항 타임라인 --------------------------------------------
def decisions_timeline(start: str, end: str, keyword: str | None = None, save: bool = True) -> str:
    n = Notion()
    pages = meetings_between(n, start, end, keyword)
    if not pages:
        return "해당 기간 회의록이 없습니다."
    md = ask_text(
        "당신은 팀의 의사결정 기록 담당자입니다. " + BASE_RULES,
        f"기간 {start} ~ {end} 회의록 {len(pages)}건입니다.\n"
        "결정사항만 날짜순 타임라인으로 정리하세요. 각 항목에 출처 회의 제목을 붙이고, "
        "번복되거나 변경된 결정은 '🔁 변경' 으로 표시하세요. 마지막에 '현재 유효한 결정 요약' 섹션.\n\n"
        + _meeting_digest(n, pages),
    )
    if save:
        _save_report(n, f"결정사항 타임라인 {start}~{end}" + (f" ({keyword})" if keyword else ""),
                     "결정사항타임라인", md, start, end)
    return md


# #5 주간 리포트 -------------------------------------------------------------
def weekly_report(end: str | None = None, save: bool = True) -> str:
    n = Notion()
    end_d = date.fromisoformat(end) if end else _today()
    start = (end_d - timedelta(days=6)).isoformat()
    end = end_d.isoformat()
    pages = meetings_between(n, start, end)

    tasks_md = ""
    if CONFIG.tasks_db:
        tasks = n.query(CONFIG.tasks_db, {"and": [
            {"property": "상태", "select": {"does_not_equal": "완료"}},
            {"property": "마감일", "date": {"on_or_before": (end_d + timedelta(days=7)).isoformat()}},
        ]})
        tasks_md = "\n".join(
            f"- {nb.prop_title(t)} / {nb.prop_text(t, '담당자') or nb.prop_text(t, '담당자명')} / "
            f"마감 {nb.prop_text(t, '마감일')} / {nb.prop_text(t, '상태')}" for t in tasks)

    md = ask_text(
        "당신은 팀장을 위한 주간 리포트 작성자입니다. " + BASE_RULES,
        f"기간 {start} ~ {end} 의 팀 위클리 리포트를 작성하세요.\n"
        "구성: # 이번 주 한눈에 (3줄) / ## 주요 결정 / ## 진행 상황·성과 / ## 리스크·이슈 / "
        "## 다음 주 마감·할 일 (담당자 포함) / ## 고객 미팅 하이라이트\n\n"
        f"<meetings>\n{_meeting_digest(n, pages)}\n</meetings>\n\n"
        f"<open_tasks>\n{tasks_md or '없음'}\n</open_tasks>",
    )
    if save:
        _save_report(n, f"주간 리포트 {start}~{end}", "주간리포트", md, start, end)
    return md


# #9 내가 놓친 회의 따라잡기 ----------------------------------------------------
def catchup(start: str, end: str, me: str, keyword: str | None = None, save: bool = False) -> str:
    n = Notion()
    pages = meetings_between(n, start, end, keyword)
    if not pages:
        return "해당 조건의 회의록이 없습니다."
    md = ask_text(
        "당신은 바쁜 팀원을 위한 회의 브리퍼입니다. " + BASE_RULES,
        f"나는 '{me}' 입니다. 아래 회의에 참석하지 못했습니다.\n"
        "나에게 중요한 것만 정확히 3줄로 알려주세요 (내 담당 업무·마감, 내 업무에 영향 주는 결정 우선). "
        "그 아래 '내 할 일' 체크리스트(- [ ] )를 덧붙이세요.\n\n" + _meeting_digest(n, pages, full=True),
        effort="low",
    )
    if save:
        _save_report(n, f"캐치업 ({me}) {start}~{end}", "캐치업", md, start, end)
    return md


# #4 브레인스토밍 → 리서치 리포트 ---------------------------------------------
def research(meeting_page_id: str, focus: str | None = None) -> str:
    n = Notion()
    text = n.page_text(meeting_page_id, depth=0)
    md = ask_text(
        "당신은 신사업 리서처입니다. 웹 검색으로 근거를 찾고, 모든 수치·주장 옆에 출처 링크를 [출처](URL) 형태로 다세요. "
        "한국어 마크다운으로 작성하세요.",
        "아래 회의에서 나온 아이디어를 기획 리포트로 발전시키세요.\n"
        + (f"집중할 주제: {focus}\n" if focus else "")
        + "구성: # 요약 / ## 아이디어별 시장성 (시장 규모, 타깃, 경쟁사, 차별점) / ## 리스크 / "
        "## 추천 우선순위와 다음 실험 / ## 출처\n\n<meeting>\n" + text + "\n</meeting>",
        effort="high", web_search=True,
    )
    page = n.create_child_page(meeting_page_id, "🔎 리서치 리포트", nb.markdown_blocks(md))
    print(f"🔎 리서치 리포트: {nb.page_url(page)}")
    return md


# #10 회의록 → SNS 카드뉴스·블로그 초안 ----------------------------------------
def content(meeting_page_id: str, brand: str | None = None) -> str:
    n = Notion()
    text = n.page_text(meeting_page_id, depth=1)
    md = ask_text(
        "당신은 콘텐츠 에디터입니다. 회의·강의 내용을 바탕으로 사실을 왜곡하지 말고 재가공하세요. "
        "한국어 마크다운으로 작성하세요.",
        (f"브랜드/채널 톤: {brand}\n" if brand else "")
        + "아래 기록으로 다음을 만드세요:\n"
        "# 인스타 카드뉴스 (2개 세트, 각 6장: 장별 헤드라인 + 본문 2줄)\n"
        "# 인스타 캡션 + 해시태그 (2개)\n"
        "# 블로그 초안 (제목 3안 + 본문 1,500자 내외, 소제목 포함)\n"
        "# 숏폼 훅 문장 5개\n\n<record>\n" + text + "\n</record>",
    )
    page = n.create_child_page(meeting_page_id, "📣 콘텐츠 초안", nb.markdown_blocks(md))
    print(f"📣 콘텐츠 초안: {nb.page_url(page)}")
    return md


# #6 회의 결정 → 위키 반영 ----------------------------------------------------
def wiki_sync(meeting_page_id: str, apply: bool = False) -> str:
    """결정된 정책 변경을 관련 위키 페이지에 반영.

    기본은 미리보기(제안만 출력). --apply 시 위키 페이지 하단에
    '회의 결정 반영' 콜아웃 + 수정 제안을 추가합니다 (기존 내용은 지우지 않음).
    """
    n = Notion()
    meeting_text = n.page_text(meeting_page_id, depth=0)
    meeting = n._req("GET", f"/pages/{meeting_page_id}")
    topics = ask_text(
        "회의록에서 정책·프로세스 변경 주제를 노션 검색 키워드로 뽑으세요. 한 줄에 하나, 최대 3개, 다른 말 없이.",
        meeting_text, effort="low",
    ).splitlines()

    reports = []
    for topic in [t.strip("-• ").strip() for t in topics if t.strip()]:
        candidates = [p for p in n.search(topic, limit=5)
                      if p["id"] != meeting_page_id and p.get("parent", {}).get("type") != "database_id"]
        if not candidates:
            reports.append(f"## {topic}\n- 관련 위키 페이지를 찾지 못했습니다.")
            continue
        wiki = candidates[0]
        wiki_text = n.page_text(wiki["id"], depth=1)
        proposal = ask_text(
            "당신은 사내 위키 관리자입니다. 회의 결정과 위키 내용이 충돌하는 부분만 찾아 수정안을 제시하세요. "
            "충돌이 없으면 정확히 '변경 불필요' 라고만 답하세요. 마크다운으로 작성하세요.",
            f"<decision_meeting>\n{meeting_text}\n</decision_meeting>\n\n"
            f"<wiki title=\"{nb.prop_title(wiki)}\">\n{wiki_text}\n</wiki>\n\n"
            "형식: ## 바뀌는 부분 (기존 → 변경) / ## 수정된 문단 (그대로 붙여넣을 수 있게)",
        )
        reports.append(f"## {topic} → {nb.prop_title(wiki)}\n{nb.page_url(wiki)}\n{proposal}")
        if apply and "변경 불필요" not in proposal[:20]:
            n.append_blocks(wiki["id"], [
                nb.divider(),
                nb.callout(f"{_today()} 회의 결정 반영 — 출처: {nb.prop_title(meeting)} "
                           f"({nb.page_url(meeting)})", "📌"),
                *nb.markdown_blocks(proposal),
            ])
            print(f"📌 위키 반영: {nb.page_url(wiki)}")
    return "\n\n".join(reports)
