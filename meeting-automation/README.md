# 🎙️ 회의 녹음 → 노션 자동화 (meeting_bot)

회의 녹음 파일 하나로 **STT 전사 → Claude 분석 → 노션 회의록 + 할 일 배정 + 핵심 일정 + 고객 히스토리**까지 한 번에 끝냅니다.
쌓인 회의록은 결정사항 타임라인·주간 리포트·리서치·위키 반영·캐치업·콘텐츠로 다시 굴러갑니다.

```
🎙️ 녹음(m4a/mp3)                         ┌─▶ 🗒️ 회의록 DB  (요약·결정사항·영문요약·전사본)
   │ STT (faster-whisper / OpenAI)         ├─▶ ✅ 할 일 DB   (담당자 @멘션 · 마감일 · 우선순위)
   ▼                                       ├─▶ 📅 핵심 일정 DB (마감·런칭·후속미팅 → 노션 캘린더) + .ics
📄 전사본 ── Claude 구조화 분석 ───────────┼─▶ 🤝 고객 CRM DB (고객콜이면 relation 으로 미팅 누적)
                                           └─▶ (옵션) 🔎 리서치 · 📣 콘텐츠 · 📌 위키 반영
매주 금요일 GitHub Actions ─────────────────▶ 📊 리포트 DB (주간 리포트)
```

## 🍎 Mac 무료 구성: Claude Code 에 "회의 시작" / "회의 끝"

Claude API 키 없이, 이미 쓰는 Claude Code 가 분석까지 합니다.

```
"회의 시작"  → Mac 마이크 녹음 (드라이브 동기화 폴더에 저장 = 자동 업로드)
"회의 끝"    → 녹음 종료 → mlx-whisper 받아쓰기 + pyannote 화자 구분 (내 Mac, 무료)
             → Claude Code 가 화자 이름 매칭·분석 (모르면 물어봄) → 미리보기
             → 노션 회의록 · 의사결정 기록 · 프로젝트 일정 반영 → 링크 안내
```

### 준비 (처음 한 번, 20분)
1. 설치 (Apple Silicon Mac)
   ```bash
   brew install ffmpeg python
   cd meeting-automation && pip install -r requirements-mac.txt
   cp .env.example .env
   ```
2. **구글 드라이브 데스크톱 앱** 설치 → 팀 드라이브 `00_관리` 안에 `녹음` 폴더 → 그 경로를 `.env` 의 `RECORD_DIR` 에.
   (Finder 에서 폴더를 터미널로 끌어다 놓으면 경로가 나옵니다)
3. **화자 구분 토큰 (무료)**: huggingface.co 가입 → `pyannote/speaker-diarization-3.1` 과
   `pyannote/segmentation-3.0` 페이지에서 이용 약관 동의 → Settings → Access Tokens 에서 Read 토큰 발급 → `.env` 의 `HF_TOKEN`.
4. **노션**: 통합 토큰을 `NOTION_TOKEN` 에, 회의록·의사결정 기록·프로젝트 일정 DB ID 를 넣고, 프로젝트 페이지에 통합 연결.
5. `MEETING_AUTHOR` 에 회의록 작성자 이름.
6. 이 폴더에서 Claude Code 실행: `cd meeting-automation && claude`
   - 처음 녹음할 때 macOS 가 마이크 권한을 물으면 허용 (터미널 / Claude 앱).

### 사용
Claude Code 에 그냥 말하면 됩니다.
- `회의 시작` (또는 `정기회의 시작`) → 🔴 녹음
- `회의 끝` → 받아쓰기 · 화자 구분 · 분석 · 미리보기 → 확인하면 노션 반영

수동으로도 쓸 수 있습니다: `python -m meeting_bot record start|stop|status|devices`, `python -m meeting_bot transcribe 파일.m4a`

### 팁
- **용어집**: `cp glossary.example.txt glossary.txt` 후 팀 용어(영어 약어, 제품명, 팀원 이름)를 한 줄에 하나씩.
  받아쓰기(Whisper)에 미리 알려 주고, 분석할 때도 잘못 받아써진 용어를 이 표기로 고칩니다. (`glossary.txt` 는 커밋되지 않음)
- 시작할 때 한 명씩 "○○○입니다" 한마디 → 화자 이름 매칭이 정확해집니다.
- 줌·구글밋 상대방 소리까지 녹음하려면 BlackHole(무료 가상 오디오) + 'Multi-Output / Aggregate Device' 를 만들고
  `record devices` 에서 그 장치 번호를 `RECORD_DEVICE=:번호` 로.
- 1시간 회의 받아쓰기는 M1/M2 기준 수 분~10분 정도. 화자 구분이 필요 없으면 `HF_TOKEN` 을 비워 두면 더 빠릅니다.

## 🧑‍🤝‍🧑 이미 있는 팀 노션에 쓰기 (project 모드)

팀 노션에 **회의록 · 의사결정 기록 · 프로젝트 일정** DB가 이미 있으면 `setup` 없이 그 DB에 바로 씁니다.

| 노션 DB | 자동으로 채우는 것 |
|---|---|
| 회의록 | 회의명(`YYMMDD_유형_주제`), 일시, 유형, 참석자, 작성자, Action Items(할 일 / 담당자 / 기한), 핵심 결정, 다음 회의 + 본문(안건 / 논의 내용 / 결정 사항 / Action Items / 다음 회의 안건 / 전체 녹취) |
| 의사결정 기록 | 중요한 결정만: 결정 사항, 결정 내용, 배경, 검토한 선택지, 근거, 결정일, 분야, 결정 참여 |
| 프로젝트 일정 | 다음 회의, 새로 정해진 마감·마일스톤·작업 기간 (같은 날짜에 같은 일정이 있으면 건너뜀) |

- 팀원 이름·회의 유형·분야는 **노션 DB의 선택지를 실행할 때 읽어 와서** 그 안에서만 고릅니다.
  코드에 팀 정보가 들어가지 않고, 노션에서 선택지를 바꾸면 자동 반영됩니다.
- 필요한 속성 이름은 `meeting_bot/project_mode.py` 맨 위에 모여 있습니다. DB 속성 이름이 다르면 거기만 고치면 됩니다.

```bash
# .env: NOTION_MEETINGS_DB / NOTION_DECISIONS_DB / NOTION_SCHEDULE_DB 에 각 DB ID
python -m meeting_bot project --audio 261028_정기회의.m4a --date 2026-10-28 --time 14:00 --author 홍길동
python -m meeting_bot project --transcript 녹취.txt --dry-run      # 노션에 쓰지 않고 결과만 확인

# 녹음 폴더 자동 감시: 새 파일이 들어오면 STT → 노션 반영 (파일명의 261028 같은 날짜를 회의 날짜로 사용)
python -m meeting_bot watch "~/Google Drive/공유 드라이브/팀폴더/00_관리/녹음" --author 홍길동
```

## 10가지 조합 ↔ 명령어

| # | 조합 | 명령 | 결과 |
|---|---|---|---|
| 1 | 회의록 → 할 일 DB 자동 연결 | `process` | 액션아이템마다 담당자(노션 멤버 자동 매칭)·마감일 붙여 할 일 DB 등록, 회의록과 relation |
| 2 | 여러 회의록 한 번에 요약 | `decisions --start 2026-10-01` | 기간 내 결정사항 타임라인 (번복된 결정 🔁 표시) |
| 3 | 회의록 → 고객 페이지 축적 | `process` (고객콜 자동 감지) | CRM 고객 행에 미팅 relation → 고객 페이지에 미팅 히스토리 |
| 4 | 회의록 → 리서치 심화 | `research <회의록ID>` / `process --research` | 웹검색 기반, 출처 달린 시장성 리포트 (회의록 하위 페이지) |
| 5 | 주간 리포트 자동 생성 | `weekly` + GitHub Actions(금 17시) | 결정·진행·리스크·다음 주 마감 정리 |
| 6 | 회의 결정 → 위키 반영 | `wiki <회의록ID> [--apply]` | 관련 위키 검색 → 충돌 부분 수정안 (기본 미리보기, `--apply` 시 위키에 추가) |
| 7 | 후속 미팅 자동 세팅 | `process --ics followup.ics` | "다음 주 팔로업" → 핵심 일정 DB(노션 캘린더) + .ics(구글/아웃룩 가져오기) |
| 8 | 한 회의, 세 개의 결과물 | `process` | 한국어 요약 + 🌐 English summary 토글 + 할 일 DB 등록 동시 처리 |
| 9 | 놓친 회의 따라잡기 | `catchup --me "김OO(마케팅)" --keyword 마케팅` | 나에게 중요한 것만 3줄 + 내 할 일 |
| 10 | 콘텐츠 파이프라인 | `content <회의록ID> --brand "슈크림마을"` / `process --content` | 카드뉴스 2세트·캡션·블로그 초안·숏폼 훅 |

`process --auto` 를 주면 회의 유형을 보고 알아서 조합합니다:
브레인스토밍 → 리서치, 강의·세미나/인터뷰 → 콘텐츠, 정책 변경 → 위키 수정안.

## 설치 (10분)

```bash
cd meeting-automation
pip install -r requirements.txt     # ffmpeg 도 필요: brew install ffmpeg / apt install ffmpeg
cp .env.example .env
```

1. **노션 통합 만들기**: https://www.notion.so/my-integrations → 새 통합 → 토큰을 `.env` 의 `NOTION_TOKEN` 에.
   (기능: 콘텐츠 읽기/수정/입력, 사용자 정보 읽기 체크)
2. **부모 페이지 연결**: 노션에 빈 페이지(예: "회의 자동화") 만들고 `···` → 연결 → 방금 만든 통합 추가.
   위키 반영(#6)을 쓰려면 위키 페이지에도 통합을 연결하세요.
3. **DB 자동 생성**:
   ```bash
   python -m meeting_bot setup <부모페이지ID>
   ```
   출력된 `NOTION_*_DB=` 값을 `.env` 에 붙여넣기. (페이지 ID = URL 끝 32자리)
4. `ANTHROPIC_API_KEY` 입력 (https://console.anthropic.com).

## 사용법

```bash
# 회의 녹음 → 노션 전체 반영 (+ 캘린더 파일)
python -m meeting_bot process --audio 2026-10-26_주간회의.m4a --date 2026-10-26 --ics followup.ics

# 이미 전사본이 있을 때 (클로바노트·줌 자막 등)
python -m meeting_bot process --transcript meeting.txt --title "A사 2차 미팅"

# 노션 AI 회의노트로 녹음했다면, 그 페이지를 그대로 입력으로
python -m meeting_bot process --notion-page <페이지ID> --auto

# 이번 분기 결정사항만 모아서
python -m meeting_bot decisions                # 기본: 분기 시작 ~ 오늘
python -m meeting_bot decisions --keyword 가격정책

# 어제 마케팅 회의, 나한테 중요한 것만
python -m meeting_bot catchup --me "박지민 (디자인)" --keyword 마케팅

# 주간 리포트
python -m meeting_bot weekly
```

## 주간 리포트 자동화 (#5)

`.github/workflows/weekly-meeting-report.yml` 가 매주 금요일 17:00(KST) 실행됩니다.
GitHub 저장소 → Settings → Secrets and variables → Actions 에 `ANTHROPIC_API_KEY`, `NOTION_TOKEN`,
`NOTION_MEETINGS_DB`, `NOTION_TASKS_DB`, `NOTION_REPORTS_DB` 를 등록하세요.

## 녹음 → 자동 실행까지 (선택)

- **폴더 감시**: 녹음 앱이 저장하는 폴더를 감시해 새 파일마다 `process --audio` 실행
  (macOS: 단축어/폴더 액션, Windows: 작업 스케줄러, Linux: `inotifywait`).
  ```bash
  inotifywait -m -e close_write --format '%w%f' ~/Recordings | while read f; do
    python -m meeting_bot process --audio "$f" --auto --ics "${f%.*}.ics"; done
  ```
- **노션 AI 회의노트** 사용 시: 노션에서 녹음·전사 → 끝나면 `process --notion-page` 로 할 일/일정/CRM 분배.

## 설계 메모

- **STT**: 기본은 로컬 `faster-whisper large-v3` (무료, 한국어 품질 좋음, GPU 있으면 실시간보다 빠름).
  노트북 CPU라면 `WHISPER_MODEL=small`, 빠르게 하려면 `STT_BACKEND=openai` (25MB 제한).
- **분석**: Claude 구조화 출력(JSON 스키마)으로 요약·결정·액션아이템·일정·정책변경·아이디어를 한 번에 뽑습니다.
  "다음 주 금요일" 같은 상대 날짜는 회의 날짜 기준으로 변환됩니다.
- **담당자 매칭**: 전사본의 이름을 노션 워크스페이스 멤버 이름과 비교해 `담당자`(people)에 지정,
  매칭이 안 되면 `담당자명`(텍스트)에만 기록합니다. 노션 프로필 이름을 회의에서 부르는 이름과 맞추면 정확도가 올라갑니다.
- **위키는 덮어쓰지 않습니다**: 기존 문서를 지우지 않고 "📌 회의 결정 반영" 콜아웃 + 수정안을 하단에 추가합니다.
- 전사본에 없는 내용은 만들지 않도록 프롬프트에 명시했지만, STT 오인식이 있을 수 있으니 처음 몇 번은 결과를 확인하세요.
