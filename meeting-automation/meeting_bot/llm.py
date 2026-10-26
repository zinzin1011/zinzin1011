"""Claude 호출 래퍼 + 회의 분석 스키마."""
import json

import anthropic

from .config import CONFIG

# 안전 분류기가 요청을 거절하면 서버에서 대체 모델로 자동 재시도
FALLBACK_BETA = "server-side-fallback-2026-07-01"

client = anthropic.Anthropic()


def _call(system: str, user: str, *, effort: str, output_config: dict | None = None,
          tools: list | None = None) -> anthropic.types.beta.BetaMessage:
    output_config = {"effort": effort, **(output_config or {})}
    messages = [{"role": "user", "content": user}]
    while True:
        with client.beta.messages.stream(
            model=CONFIG.claude_model,
            max_tokens=64000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config=output_config,
            system=system,
            messages=messages,
            **({"tools": tools} if tools else {}),
        ) as stream:
            msg = stream.get_final_message()
        # 웹검색 등 서버 도구가 길어지면 pause_turn 으로 끊겨 옴 → 이어서 진행
        if msg.stop_reason == "pause_turn":
            messages = messages + [{"role": "assistant", "content": msg.content}]
            continue
        if msg.stop_reason == "refusal":
            raise RuntimeError("Claude 가 요청을 처리하지 못했습니다 (refusal).")
        if msg.stop_reason == "max_tokens":
            raise RuntimeError("응답이 max_tokens 에서 잘렸습니다. 입력을 나눠서 실행하세요.")
        return msg


def _text(msg) -> str:
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def ask_text(system: str, user: str, *, effort: str = "medium", web_search: bool = False) -> str:
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 15}] if web_search else None
    return _text(_call(system, user, effort=effort, tools=tools))


def ask_json(system: str, user: str, schema: dict, *, effort: str = "medium") -> dict:
    msg = _call(
        system, user, effort=effort,
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    return json.loads(_text(msg))


# ---------------------------------------------------------------------------
# 회의 분석 스키마
# ---------------------------------------------------------------------------

def _obj(props: dict) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


_STR = {"type": "string"}
_NSTR = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_STRS = {"type": "array", "items": _STR}

MEETING_SCHEMA = _obj({
    "title": _STR,
    "meeting_type": {"type": "string", "enum": ["내부회의", "고객콜", "브레인스토밍", "강의·세미나", "인터뷰", "기타"]},
    "attendees": _STRS,
    "customer_name": _NSTR,
    "summary": _STRS,
    "summary_en": _STRS,
    "decisions": {"type": "array", "items": _obj({"decision": _STR, "rationale": _STR})},
    "action_items": {"type": "array", "items": _obj({
        "task": _STR,
        "owner": _NSTR,
        "due_date": _NSTR,
        "priority": {"type": "string", "enum": ["높음", "보통", "낮음"]},
    })},
    "key_events": {"type": "array", "items": _obj({
        "title": _STR,
        "date": _STR,
        "time": _NSTR,
        "kind": {"type": "string", "enum": ["마감", "런칭", "미팅", "후속미팅", "기타"]},
        "attendees": _STRS,
        "agenda": _STR,
    })},
    "policy_changes": {"type": "array", "items": _obj({"topic": _STR, "change": _STR})},
    "ideas": _STRS,
    "open_questions": _STRS,
    "tags": _STRS,
})

MEETING_SYSTEM = """당신은 한국어 회의록 정리 전문가입니다. STT 전사본은 오탈자·화자 누락이 있을 수 있으니 문맥으로 보정하세요.

규칙:
- 전사본에 없는 사실은 만들지 마세요. 불확실하면 null 이나 빈 배열.
- summary: 핵심 3~5줄 (한국어). summary_en: 같은 내용 영어 번역.
- decisions: '하기로 했다/확정/결정' 류만. 논의만 된 건 open_questions 로.
- action_items: 담당자(owner)는 전사본에 나온 이름 그대로. 마감일은 YYYY-MM-DD.
  "다음 주 금요일", "월말" 같은 상대 날짜는 회의 날짜 기준으로 계산하세요.
- key_events: 마감·런칭·외부 미팅 등 캘린더에 올릴 핵심 일정, 그리고 "다음 주 팔로업 필요" 같은
  후속 미팅(kind=후속미팅). 날짜는 YYYY-MM-DD, 시간은 HH:MM 또는 null.
  후속 미팅 날짜가 명시되지 않았으면 회의 날짜 기준 합리적인 영업일을 제안하세요.
- policy_changes: 정책·프로세스·규칙이 바뀐 결정 (위키 반영 대상).
- customer_name: 외부 고객사와의 콜이면 고객사명, 아니면 null.
- ideas: 브레인스토밍에서 나온 아이디어 (리서치 대상).
"""


def analyze_meeting(transcript: str, meeting_date: str, hint_title: str | None = None) -> dict:
    user = (
        f"회의 날짜: {meeting_date}\n"
        + (f"회의 제목(참고): {hint_title}\n" if hint_title else "")
        + f"\n<transcript>\n{transcript}\n</transcript>"
    )
    return ask_json(MEETING_SYSTEM, user, MEETING_SCHEMA, effort="high")
