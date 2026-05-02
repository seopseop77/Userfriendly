# Claude Code 작업 지침 (CLAUDE.md)

이 문서는 **Claude Code가 이 리포지토리에서 작업할 때 따라야 하는 규칙**을 정의한다.
전략·설계 논의는 Claude Cowork에서 진행되고, 이 문서와 `docs/` 하위 문서들에 결론이
반영된다. Claude Code는 여기서 **구현**을 담당한다.

## 1. 프로젝트 한 눈에 보기

- **목적**: Claude Code 같은 CLI 코딩 에이전트와 LLM API 서버 사이에 끼우는 로컬
  사이드카 프록시 **프레임워크**. 코어는 hook 점·capability·egress 통제만 제공하고
  *기능*(scope guard, drift 추적, 데이터 업로드 등)은 모두 **플러그인**으로 구현.
- **세 가지 핵심 원칙** (충돌 시 위에서부터):
  1. 확장성 우선 — 새 기능 = 코어 수정 없이 플러그인 추가.
  2. 보안 우선 — 데이터 egress 기본 OFF, capability 명시 승인, 모든 행동 audit.
  3. 모드 인지 — L(local-only)/A(audit-light)/R(research) 모드별 capability 강제.
- **배포 형태**: 로컬 사이드카. 협업자들이 플러그인 추가로 기능을 확장.
- **언어/스택**: Python 3.11+, FastAPI, httpx, SQLite, Alembic.
- **스코프**: 코어는 Claude Code(Anthropic Messages API) 우선. 어댑터 추상화만
  열어두고 OpenAI/Gemini 구현은 후순위. 도메인 기능은 코어 밖 — 플러그인.

자세한 설계는 `docs/design.md` (특히 §4 핵심 원칙, §6 아키텍처, §7 보안 모델),
플러그인 작성은 `docs/plugins.md`. 결정을 임의로 뒤집지 말 것 — ADR 거치기.

## 2. 역할 분담 (중요)

| 영역 | 주체 | 산출물 |
|---|---|---|
| 프로젝트 방향, 아키텍처 결정, 스코프 조정 | 사람 + Claude Cowork | `docs/design.md`, `docs/decisions/*.md` |
| 코드 구현, 리팩토링, 테스트, 버그 수정 | Claude Code | `src/`, `tests/`, `docs/worklog/*.md` |

**Claude Code는 아키텍처를 바꾸는 결정을 혼자 내리지 않는다.** 예: 새 의존성 추가,
저장소 스키마 변경, 프록시 동작 방식 변경, 공개 인터페이스(CLI 플래그, 환경변수,
이벤트 스키마) 변경. 이런 게 필요하다고 판단되면 **작업을 멈추고** 워크로그에
"decision needed" 섹션을 쓴 뒤 사용자에게 알린다.

## 3. 작업 추적 (필수)

본 프로젝트는 사용량 제한·세션 cutoff가 잦다고 가정한다. **세션이 갑자기 끊겨도
다음 세션이 잃는 정보가 거의 없도록** 일하는 게 규약의 목적이다.

### 3.1 세 개의 진입점

| 파일 | 역할 | 누가 갱신 |
|---|---|---|
| `docs/STATUS.md` | "지금 어디 와 있나" 한 페이지. 새 세션의 첫 진입점. | 매 체크포인트마다 |
| `docs/worklog/<YYYY-MM-DD>-<slug>.md` | 현 세션의 작업 일지. 의도·결정·검증 등 *서사*. | 매 의미 단위 작업마다 |
| git log | 코드 차원의 체크포인트. *정확히 무엇이 바뀌었는지*. | 매 commit마다 (자동) |

세 개가 서로를 가리킨다(STATUS는 worklog와 commit 해시를 가리키고, worklog는 commit
해시를 인용하고, commit은 worklog를 Refs로). 한 군데만 봐도 다른 두 개로 점프 가능.

### 3.2 워크로그 규칙

- 위치: `docs/worklog/YYYY-MM-DD-<slug>.md`
- 템플릿: `docs/worklog/TEMPLATE.md`
- 한 세션에 여러 작업을 하면 같은 파일에 합친다(같은 날짜 + 같은 주제).
- 주제가 바뀌면 새 파일.
- **작업 완료 시점이 아니라 작업 중에 갱신**한다. cutoff에 대비.

워크로그에 반드시 포함:
- 요청(사용자가 시킨 것)과 의도 해석
- 수정/생성한 파일 목록 (경로 + 한 줄 요약 + 관련 commit 해시)
- 내린 결정과 근거
- 검증(테스트/실행/수동확인) 내용과 결과
- 남은 일, 알려진 한계, **"이어받는 사람에게"** 섹션

### 3.3 체크포인트 규칙 (cutoff 대비)

다음 시점 *각각이 하나의 체크포인트*다. 체크포인트마다 **세 개를 한 단위로** 처리한다.

체크포인트 시점:
- 의미 있는 코드 변경 단위가 끝났을 때
- 테스트가 새로 통과했을 때
- 의존성/마이그레이션을 추가한 직후
- 한 작업 단위(roadmap 체크리스트 한 줄)가 끝났을 때
- **사용자가 "체크포인트" 또는 "pause"를 요청했을 때**

매 체크포인트의 세 단위:

1. **코드 commit** — CLAUDE.md §9 규칙대로.
2. **워크로그 갱신** — "한 일" 섹션에 새 commit 해시 추가, "남은 일/이어받는 사람"
   섹션을 *현재 시점 기준*으로 다시 쓴다. 작업 도중에 적었던 옛 메모는 두지 말 것.
3. **STATUS.md 갱신** — 최종 업데이트 시각, 활성 worklog 경로, 최근 커밋 3–5개,
   "지금 멈춘 위치", "다음 한 걸음"을 갱신.

이 셋을 한 atomic unit으로 처리하지 않으면 cutoff 시 다음 세션이 길을 잃는다.

### 3.4 ADR

아키텍처 수준의 결정은 워크로그 대신 **ADR**.

- 위치: `docs/decisions/NNNN-<slug>.md`
- 템플릿: `docs/decisions/TEMPLATE.md`
- ADR은 되돌리기 어려운/영향이 넓은 결정에만. 사소한 구현 선택은 워크로그로 충분.

## 4. 작업 전 체크리스트

새 작업을 시작할 때마다:

1. **`docs/STATUS.md` 를 가장 먼저 읽는다.** 거기서 가리키는 worklog와 다음 한
   걸음을 확인.
2. STATUS가 가리키는 worklog를 읽고, 마지막 "이어받는 사람에게" 섹션을 본다.
3. `git log -5 --oneline` 로 최근 commit 흐름 확인. 필요하면 마지막 commit의
   `git show` 로 차이 확인.
4. `docs/design.md`, `docs/roadmap.md` 에서 현 phase의 우선순위 재확인.
5. 관련 ADR(`docs/decisions/`) 확인.
6. **시작 전 한 줄 announce**: "STATUS.md에 적힌 다음 한 걸음 = X. 지금부터 그것을
   시작합니다." 사용자가 다른 걸 원하면 그 시점에 끼어들 수 있게.
7. 불분명하거나 아키텍처에 영향 주는 부분이 있으면 **작업 시작 전** 사용자에게 질문.

### 4.1 표준 "이어받기" 프롬프트

사용자가 새 Claude Code 세션을 열고 다음 한 줄만 던지면 위 절차가 자동 실행된다:

> 이어받기. STATUS.md → 거기 적힌 worklog → `git log -5` 순서로 읽고, "다음 한
> 걸음"을 한 줄로 announce 후 그대로 수행해. 도중에 §3.3 체크포인트 규칙대로
> 갱신하면서 진행.

## 5. 코드/구현 규약

- Python 3.11+ 문법 가정. 타입 힌트는 가능하면 쓰고, public 함수/클래스는 필수.
- 포매터/린터: `ruff` (format + lint). 커밋 전 항상 실행.
- 테스트: `pytest`. 순수 함수는 단위 테스트, 프록시 동작은 통합 테스트 (가짜
  Anthropic 서버 띄워서 end-to-end).
- 비동기 기본(`async def`). 블로킹 IO 금지.
- 로깅은 `structlog`. print 쓰지 말 것.
- 설정은 `pydantic-settings` 기반. 환경변수 이름은 `LLMTRACK_*` 접두사.
- 시크릿/PII는 로그에도 남기지 않는다. 스크러빙은 `llm_tracker.scrubbers`에서만.
- 파일 상단 주석은 과하게 달지 말 것. 모듈 docstring은 OK.

## 6. 검증 (Verify) 규약

"작업 완료"라고 보고하기 전에 최소 한 가지의 **능동적 검증**이 있어야 한다.

- 함수 추가/수정 → 해당 테스트 실행 결과를 워크로그에 복붙.
- 프록시 동작 변경 → 로컬에서 실제 플로우를 재현한 로그/스크린샷.
- 문서만 수정 → 관련 링크가 깨지지 않는지 확인.
- 의존성 추가 → `pip install -e .` 또는 동등 절차가 깨끗하게 끝나는지 확인.

"테스트는 통과할 것으로 보인다" 같은 추정형 진술 금지. 실행하거나, 못 했으면 못 했다고 쓴다.

## 7. 스코프 드리프트 방지

- 요청되지 않은 리팩토링·최적화 금지. 눈에 띄는 개선점은 워크로그에 "제안" 섹션으로 적어두되 손대지 않는다.
- 포매팅 대량 변경을 기능 PR에 섞지 말 것. 분리.
- 요청이 모호하면 **최소 스코프**로 해석하고 질문한다.

## 8. 공개 인터페이스

아래 항목은 "바뀌면 하위 시스템·플러그인 생태가 깨지는" 계약이다. 변경은 ADR 필수.

- CLI 명령 이름 및 플래그 (`llm-tracker ...`)
- 환경변수 이름 (`LLMTRACK_*`, `ANTHROPIC_BASE_URL` 포함)
- 프록시가 듣는 경로 (Anthropic Messages API 모양을 따름)
- **Hook 라이프사이클** (8개 hook의 이름·시점·반환값 의미)
- **Capability 어휘** (capability 이름·의미)
- **Plugin manifest 스키마** (`plugin.toml` 키와 검증 규칙)
- **콘텐츠 레벨 정의** (L0/L1/L2/L3)
- 코어 SQLite 스키마 (`exchanges`, `events`, `tool_calls`, `audit_log`)
- 모드별 capability 정책 (L/A/R 각각 무엇이 허용/거부되는지)
- 서명 검증 규칙(plugin manifest, TaskDefinition 등)

## 9. Git 커밋 규칙 (자동 커밋 활성)

Claude Code는 비자명한 변경 단위마다 **자동으로 git commit**한다.
**`git push`는 절대 자동으로 하지 않는다** — 사람이 직접 한다.

### 커밋 시점

- 워크로그 엔트리의 한 작업 단위가 완료될 때마다.
- 의존성 변경(`pyproject.toml` 수정 + lock 갱신) 후.
- Alembic 마이그레이션 추가 후.
- 테스트가 통과한 직후. 실패 상태로 커밋 금지.

작업 도중 임시 상태(빌드 깨짐, 테스트 실패)는 **커밋하지 않는다**. 그런 경우엔
`docs/worklog/`만 업데이트하고 다음 단계로 넘어간다.

### 커밋 메시지 형식

```
<scope>: <한 줄 요약 (50자 이내)>

- 변경한 핵심 내용 1
- 변경한 핵심 내용 2

Refs: docs/worklog/YYYY-MM-DD-<slug>.md
ADR: docs/decisions/NNNN-<slug>.md     (해당 시)
```

`<scope>` 예시: `proxy`, `server`, `scope-guard`, `storage`, `docs`, `infra`,
`deps`, `tests`.

**커밋 메시지에 자동 생성된 메타(예: "Generated with X", "Co-Authored-By: …")를
넣지 말 것.** 깔끔한 메시지만.

### 스테이징

- 의도한 파일만 스테이징. `git add -A`보단 명시적 경로.
- 자동 생성/캐시 파일은 즉시 `.gitignore`에 추가하고 커밋에서 제외.
- 커밋 전 `git diff --cached` 확인. **시크릿 정규식 검토 필수**:
  `Bearer `, `sk-`, `AKIA`, `ghp_`, `xoxb-`, `password=`, `LLMTRACK_*_TOKEN=`,
  이메일 패턴 등.

### 금지 사항

- `git push` 자동 실행.
- `git push --force` / `--force-with-lease` 자동 실행.
- 히스토리 재작성(`rebase -i`, `commit --amend`) 자동 실행.
- 사용자 확인 없이 대량 파일 삭제 커밋.
- `.env`·키체인·secret 파일 커밋.

### 워크로그와의 연계

워크로그 "한 일" 섹션엔 커밋 짧은 해시를 함께 적는다:

```
## 한 일
- 생성: src/foo.py — bar 처리 (commit a1b2c3d)
- 수정: tests/test_foo.py (commit a1b2c3d, e4f5g6h)
```

이렇게 두면 워크로그를 읽다가 "정확히 뭘 바꿨지?"가 궁금할 때 git에서 바로
diff를 볼 수 있다.

## 10. 자주 쓸 커맨드 (채워나갈 것)

```bash
# 의존성 설치 (계획; Phase 0 구현 후 실제 동작 확인 필요)
pip install -e ".[dev]"

# 포맷 + 린트
ruff format . && ruff check .

# 테스트
pytest -q

# 프록시 로컬 기동 (계획)
python -m llm_tracker.proxy

# 중앙 서버 로컬 기동 (계획; Supabase에 연결)
DATABASE_URL=$SUPABASE_URL python -m llm_tracker_server

# Alembic 마이그레이션 (계획)
alembic revision -m "<message>"
alembic upgrade head
```

## 11. 파일 찾기 힌트

```
src/llm_tracker/             # 로컬 사이드카 프록시
  proxy/        # FastAPI 앱, SSE 포워딩, tee 스트림
  adapters/     # provider-specific 파싱 (지금은 anthropic만)
  extractors/   # SSE 이벤트 → 구조화 레코드
  scope_guard/  # task-scope 판정 (embedding + LLM judge)
  scrubbers/    # PII/시크릿 제거
  storage/      # SQLite 로컬 버퍼, 중앙 업로드 클라이언트
  config/       # pydantic-settings
  cli/          # Typer CLI

src/llm_tracker_server/      # 중앙 서버 (Supabase + Fly.io 배포)
  api/          # HTTP 라우트 (얇게)
  domain/       # 비즈니스 로직 (DB 모름)
  storage/      # SQLAlchemy + Alembic
  analytics/    # 분석 쿼리 (ClickHouse 후보)
  signing/      # ed25519 서명 헬퍼

tests/          # pytest
docs/           # 사람이 읽는 문서
  STATUS.md     # 새 세션의 첫 진입점 — "지금 어디 와 있나"
  worklog/      # 매 세션 작업 일지
  decisions/    # ADR
.claude/        # Claude Code 전용 설정 (슬래시 커맨드 등)
```

현재는 뼈대만 있다. 채워 나가는 건 Claude Code의 일.
