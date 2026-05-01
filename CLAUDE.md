# Claude Code 작업 지침 (CLAUDE.md)

이 문서는 **Claude Code가 이 리포지토리에서 작업할 때 따라야 하는 규칙**을 정의한다.
전략·설계 논의는 Claude Cowork에서 진행되고, 이 문서와 `docs/` 하위 문서들에 결론이
반영된다. Claude Code는 여기서 **구현**을 담당한다.

## 1. 프로젝트 한 눈에 보기

- **목적**: Claude Code 같은 CLI 코딩 에이전트와 LLM API 서버 사이에 로컬 프록시를
  끼워 (a) 입출력을 구조화·저장하고, (b) 사용자가 등록된 작업 범위 밖의 요청을 하면
  자동으로 차단한다(task-scope enforcement). 모델의 이상 거동에 대한 응답측 개입은
  후순위.
- **배포 형태**: 연구 인원에게만 제공되는 로컬 사이드카(공개 배포 아님).
- **언어/스택**: Python 3.11+. 웹 프레임워크는 FastAPI, HTTP 클라이언트는 httpx.
  자세한 근거는 `docs/decisions/0001-python-fastapi-httpx.md`.
- **스코프**: 지금은 Claude Code(= Anthropic Messages API)만. 다른 프로바이더(OpenAI,
  Gemini)는 어댑터 레이어로 추상화만 해두고 실제 구현은 후순위.

자세한 설계는 `docs/design.md`를 읽고 시작하라. 여기에 적힌 결정을 임의로 뒤집지 말 것.

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

Claude Code의 모든 비자명한 작업 세션은 **워크로그 엔트리**를 남긴다.

- 위치: `docs/worklog/YYYY-MM-DD-<slug>.md`
- 템플릿: `docs/worklog/TEMPLATE.md`
- 한 세션에 여러 작업을 하면 하나의 파일에 합친다(같은 날짜 + 같은 주제).
- 주제가 바뀌면 새 파일.
- **완료 후가 아니라 작업 중에도 업데이트**한다. 중단되어도 이어받을 수 있어야 한다.

워크로그에 반드시 포함할 것:
- 요청(사용자가 시킨 것)과 의도 해석
- 수정/생성한 파일 목록 (경로 + 한 줄 요약)
- 내린 결정과 근거
- 검증(테스트/실행/수동확인) 내용과 결과
- 남은 일, 알려진 한계, 이어받을 사람을 위한 힌트

아키텍처 수준의 결정은 워크로그가 아니라 **ADR**로 남긴다.

- 위치: `docs/decisions/NNNN-<slug>.md` (NNNN = 4자리 증분 번호)
- 템플릿: `docs/decisions/TEMPLATE.md`
- ADR은 되돌리기 어려운/영향이 넓은 결정에만 쓴다. 사소한 구현 선택은 워크로그로 충분.

## 4. 작업 전 체크리스트

새 작업을 시작할 때마다:

1. `docs/design.md`, `docs/roadmap.md`에서 지금이 어느 단계이며 무엇이 우선순위인지 확인.
2. 같은 주제의 최근 워크로그가 있는지 `docs/worklog/` 확인 (이어받기).
3. 관련 ADR이 있는지 `docs/decisions/` 확인.
4. 불분명하거나 아키텍처에 영향 주는 부분이 있으면 **작업 시작 전** 사용자에게 질문.

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

아래 항목은 "바뀌면 하위 시스템이 깨지는" 계약이다. 변경은 ADR 필수.

- CLI 명령 이름 및 플래그 (`llm-tracker ...`)
- 환경변수 이름 (`LLMTRACK_*`, `ANTHROPIC_BASE_URL` 포함)
- 프록시가 듣는 경로 (Anthropic Messages API 모양을 따름)
- 이벤트 스키마 (`docs/design.md` §데이터 모델)
- 로컬 저장소(SQLite) 스키마 (`task_definitions`, `scope_verdicts` 포함)
- 중앙 업로드 API 스키마
- TaskDefinition 포맷 및 서명 검증 규칙

## 9. 자주 쓸 커맨드 (채워나갈 것)

```bash
# 의존성 설치 (계획; Phase 0 구현 후 실제 동작 확인 필요)
pip install -e ".[dev]"

# 포맷 + 린트
ruff format . && ruff check .

# 테스트
pytest -q

# 프록시 로컬 기동 (계획)
python -m llm_tracker.proxy
```

## 10. 파일 찾기 힌트

```
src/llm_tracker/
  proxy/        # FastAPI 앱, SSE 포워딩, tee 스트림
  adapters/     # provider-specific 파싱 (지금은 anthropic만)
  extractors/   # SSE 이벤트 → 구조화 레코드
  scrubbers/    # PII/시크릿 제거
  storage/      # SQLite 로컬 버퍼, 중앙 업로드 클라이언트
  config/       # pydantic-settings
  cli/          # Typer CLI
tests/          # pytest
docs/           # 사람이 읽는 문서
.claude/        # Claude Code 전용 설정 (슬래시 커맨드 등)
```

현재는 뼈대만 있다. 채워 나가는 건 Claude Code의 일.
