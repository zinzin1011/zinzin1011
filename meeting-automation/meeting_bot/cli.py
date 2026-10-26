"""명령줄 진입점: python -m meeting_bot <명령> ..."""
import argparse
from datetime import date, timedelta
from pathlib import Path

from . import features
from .notion import Notion


def _quarter_start(d: date) -> str:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1).isoformat()


def cmd_setup(args):
    from .setup_notion import setup
    ids = setup(args.parent_page_id)
    print("\n.env 에 아래 값을 붙여넣으세요:\n")
    for k, v in ids.items():
        print(f"{k}={v}")


def cmd_process(args):
    from .pipeline import process_transcript

    if args.audio:
        from .stt import transcribe
        print(f"🎙️ STT 변환 중: {args.audio}")
        transcript = transcribe(args.audio)
        Path(args.audio).with_suffix(".txt").write_text(transcript, encoding="utf-8")
    elif args.transcript:
        transcript = Path(args.transcript).read_text(encoding="utf-8")
    else:  # 노션 AI 회의노트 등 이미 노션에 있는 기록
        transcript = Notion().page_text(args.notion_page, depth=3)

    ics = Path(args.ics) if args.ics else None
    result = process_transcript(transcript, args.date, args.title, ics)
    a, meeting_id = result["analysis"], result["meeting"]["id"]

    # 회의 유형에 따라 후속 조합 자동 실행
    if args.auto or args.research:
        if a["ideas"] and (args.research or a["meeting_type"] == "브레인스토밍"):
            features.research(meeting_id)
    if args.auto or args.content:
        if args.content or a["meeting_type"] in ("강의·세미나", "인터뷰"):
            features.content(meeting_id, args.brand)
    if args.auto or args.wiki:
        if a["policy_changes"]:
            print(features.wiki_sync(meeting_id, apply=args.apply_wiki))


def _load_transcript(args) -> str:
    if args.audio:
        from .stt import transcribe
        print(f"🎙️ STT 변환 중: {args.audio}")
        text = transcribe(args.audio)
        Path(args.audio).with_suffix(".txt").write_text(text, encoding="utf-8")
        return text
    if args.transcript:
        return Path(args.transcript).read_text(encoding="utf-8")
    return Notion().page_text(args.notion_page, depth=3)


def cmd_project(args):
    import json
    from .project_mode import process_project_meeting
    result = process_project_meeting(_load_transcript(args), args.date, args.time, args.author, args.dry_run)
    if args.dry_run:
        print(json.dumps(result["analysis"], ensure_ascii=False, indent=2))


def cmd_watch(args):
    from .stt import transcribe
    from .watch import watch

    def handle(path, day):
        text = transcribe(path)
        path.with_suffix(".txt").write_text(text, encoding="utf-8")
        if args.mode == "project":
            from .project_mode import process_project_meeting
            process_project_meeting(text, day, author=args.author)
        else:
            from .pipeline import process_transcript
            process_transcript(text, day)

    watch(args.folder, handle, args.interval)


def cmd_decisions(args):
    today = date.today()
    print(features.decisions_timeline(args.start or _quarter_start(today),
                                      args.end or today.isoformat(), args.keyword, not args.no_save))


def cmd_weekly(args):
    print(features.weekly_report(args.end, not args.no_save))


def cmd_catchup(args):
    day = args.date or (date.today() - timedelta(days=1)).isoformat()
    print(features.catchup(args.start or day, args.end or day, args.me, args.keyword, args.save))


def cmd_research(args):
    print(features.research(args.page_id, args.focus))


def cmd_content(args):
    print(features.content(args.page_id, args.brand))


def cmd_wiki(args):
    print(features.wiki_sync(args.page_id, apply=args.apply))


def main():
    p = argparse.ArgumentParser(prog="meeting_bot", description="회의 녹음 → 노션 자동화")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="노션 DB 5개 생성")
    s.add_argument("parent_page_id", help="DB를 만들 부모 페이지 ID (통합 연결 필수)")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("process", help="회의 1건 처리: STT → 회의록·할 일·일정·CRM")
    src = s.add_mutually_exclusive_group(required=True)
    src.add_argument("--audio", help="녹음 파일 (m4a, mp3, wav ...)")
    src.add_argument("--transcript", help="이미 있는 전사 텍스트 파일")
    src.add_argument("--notion-page", help="노션 AI 회의노트 등 전사본이 있는 페이지 ID")
    s.add_argument("--date", help="회의 날짜 YYYY-MM-DD (기본: 오늘)")
    s.add_argument("--title", help="회의 제목 (기본: 자동 생성)")
    s.add_argument("--ics", help="핵심 일정을 .ics 파일로도 저장 (캘린더 앱 가져오기용)")
    s.add_argument("--auto", action="store_true", help="회의 유형 보고 리서치/콘텐츠/위키 자동 실행")
    s.add_argument("--research", action="store_true", help="아이디어 리서치 리포트 생성")
    s.add_argument("--content", action="store_true", help="SNS·블로그 콘텐츠 초안 생성")
    s.add_argument("--brand", help="콘텐츠 톤 (예: '슈크림마을, 친근한 반말')")
    s.add_argument("--wiki", action="store_true", help="정책 변경을 위키에 반영할 제안 출력")
    s.add_argument("--apply-wiki", action="store_true", help="위키 페이지에 실제로 추가")
    s.set_defaults(func=cmd_process)

    s = sub.add_parser("project", help="팀 프로젝트 노션(회의록·의사결정 기록·프로젝트 일정)에 반영")
    src = s.add_mutually_exclusive_group(required=True)
    src.add_argument("--audio"); src.add_argument("--transcript"); src.add_argument("--notion-page")
    s.add_argument("--date", help="회의 날짜 YYYY-MM-DD (기본: 오늘)")
    s.add_argument("--time", help="회의 시작 시각 HH:MM")
    s.add_argument("--author", help="작성자 (노션 '작성자' 선택지 중 하나)")
    s.add_argument("--dry-run", action="store_true", help="노션에 쓰지 않고 분석 결과만 출력")
    s.set_defaults(func=cmd_project)

    s = sub.add_parser("watch", help="녹음 폴더 감시 → 새 파일 자동 처리")
    s.add_argument("folder", help="녹음 파일이 쌓이는 폴더 (구글 드라이브 동기화 폴더 추천)")
    s.add_argument("--mode", choices=["project", "default"], default="project")
    s.add_argument("--author", help="작성자 (project 모드)")
    s.add_argument("--interval", type=int, default=60, help="확인 주기(초)")
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser("decisions", help="기간 내 결정사항 타임라인 (기본: 이번 분기)")
    s.add_argument("--start"); s.add_argument("--end"); s.add_argument("--keyword")
    s.add_argument("--no-save", action="store_true")
    s.set_defaults(func=cmd_decisions)

    s = sub.add_parser("weekly", help="주간 리포트 (기본: 최근 7일)")
    s.add_argument("--end", help="리포트 마지막 날 YYYY-MM-DD")
    s.add_argument("--no-save", action="store_true")
    s.set_defaults(func=cmd_weekly)

    s = sub.add_parser("catchup", help="놓친 회의 3줄 요약 (기본: 어제)")
    s.add_argument("--me", required=True, help="내 이름/역할")
    s.add_argument("--date"); s.add_argument("--start"); s.add_argument("--end")
    s.add_argument("--keyword", help="예: 마케팅")
    s.add_argument("--save", action="store_true")
    s.set_defaults(func=cmd_catchup)

    s = sub.add_parser("research", help="회의록 아이디어 → 출처 달린 리서치 리포트")
    s.add_argument("page_id"); s.add_argument("--focus")
    s.set_defaults(func=cmd_research)

    s = sub.add_parser("content", help="회의록 → 카드뉴스·블로그 초안")
    s.add_argument("page_id"); s.add_argument("--brand")
    s.set_defaults(func=cmd_content)

    s = sub.add_parser("wiki", help="회의 결정 → 관련 위키 수정안 (기본 미리보기)")
    s.add_argument("page_id"); s.add_argument("--apply", action="store_true")
    s.set_defaults(func=cmd_wiki)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
