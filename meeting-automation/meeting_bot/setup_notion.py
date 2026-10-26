"""노션에 필요한 DB 5개를 한 번에 생성.

부모 페이지에 통합(Integration)을 먼저 연결해야 합니다:
페이지 우측 상단 ··· → 연결(Connections) → 내 통합 선택.
"""
from .notion import Notion


def _select(*names: str) -> dict:
    return {"select": {"options": [{"name": n} for n in names]}}


def _relation(db_id: str) -> dict:
    # dual_property: 상대 DB에도 역방향 relation 이 생겨 양쪽에서 히스토리가 보임
    return {"relation": {"database_id": db_id, "type": "dual_property", "dual_property": {}}}


def setup(parent_page_id: str) -> dict[str, str]:
    n = Notion()

    crm = n.create_database(parent_page_id, "🤝 고객 CRM", {
        "고객사": {"title": {}},
        "담당자": {"rich_text": {}},
        "단계": _select("리드", "미팅중", "제안", "계약", "보류"),
        "메모": {"rich_text": {}},
    })
    meetings = n.create_database(parent_page_id, "🗒️ 회의록", {
        "제목": {"title": {}},
        "날짜": {"date": {}},
        "유형": _select("내부회의", "고객콜", "브레인스토밍", "강의·세미나", "인터뷰", "기타"),
        "참석자": {"multi_select": {"options": []}},
        "태그": {"multi_select": {"options": []}},
        "요약": {"rich_text": {}},
        "결정사항": {"rich_text": {}},
        "고객": _relation(crm["id"]),
    })
    tasks = n.create_database(parent_page_id, "✅ 할 일", {
        "할 일": {"title": {}},
        "담당자": {"people": {}},
        "담당자명": {"rich_text": {}},
        "마감일": {"date": {}},
        "상태": _select("할 일", "진행 중", "완료"),
        "우선순위": _select("높음", "보통", "낮음"),
        "회의록": _relation(meetings["id"]),
    })
    schedule = n.create_database(parent_page_id, "📅 핵심 일정", {
        "일정": {"title": {}},
        "날짜": {"date": {}},
        "구분": _select("마감", "런칭", "미팅", "후속미팅", "기타"),
        "참석자": {"rich_text": {}},
        "안건": {"rich_text": {}},
        "회의록": _relation(meetings["id"]),
    })
    reports = n.create_database(parent_page_id, "📊 리포트", {
        "제목": {"title": {}},
        "기간": {"date": {}},
        "종류": _select("주간리포트", "결정사항타임라인", "리서치", "콘텐츠", "캐치업", "위키반영"),
    })

    return {
        "NOTION_MEETINGS_DB": meetings["id"],
        "NOTION_TASKS_DB": tasks["id"],
        "NOTION_SCHEDULE_DB": schedule["id"],
        "NOTION_CRM_DB": crm["id"],
        "NOTION_REPORTS_DB": reports["id"],
    }
