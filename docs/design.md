# 설계 문서 — LLM 트래픽 관측/개입 프록시

**상태**: Draft v0.1 (2026-04-25, 초기 세팅)
**오너**: 이민섭
**범위**: Claude Code를 대상으로 한 로컬 사이드카 프록시. 다른 CLI 에이전트는
어댑터 레이어로만 추상화하고 구현은 후순위.

---

## 1. 프로젝트 맥락

상위 프로젝트의 목표는 두 축이다.

1. 외부에 완전히 공개되지 않는 상용 LLM(Claude 등)의 내부 변화(토큰 사용량, 성능,
   거동)를 지속 추적해 데이터를 수집한다.
2. 수집한 데이터·정책을 토대로 LLM 사용에 **개입**할 수 있는 제어 계층을 만든다.
   개입의 1차 구체적 형태는 **작업 범위 강제(task-scope enforcement)** 다.
   사용자가 등록된 작업(연구 주제, 회사 업무 등)과 무관한 요청을 하면 프록시가
   자동으로 그 요청에 대한 답변을 차단한다. 모델 자체의 이상 행동을 보고 abort
   하는 류의 응답측 개입은 후순위.

이 리포지토리는 그중에서 **관측/수집/범위 강제의 실행 경로**를 담당한다. 지표 설계와
질문 세트 큐레이션은 다른 구성원의 작업이다.

## 2. 설계 결정(잠정 확정)

| # | 항목 | 결정 | 비고 |
|---|---|---|---|
| 1 | 배포 형태 | 사용자 로컬 사이드카 프록시 + 중앙 데이터 수집 | `docs/decisions/` 참조 |
| 2 | 언어/런타임 | Python 3.11+ | `0001-python-fastapi-httpx.md` |
| 3 | 대상 에이전트 | Claude Code (Anthropic Messages API) 우선 | 어댑터 레이어로 추상화 |
| 4 | 사용자 범위 | 선별된 연구 인원만 (공개 배포 아님) | 동의/인증은 간소화 가능 |
| 5 | 오픈소스 여부 | **미정** (프로젝트 성격 확정 후 재검토) | 지금은 internal로 취급 |

## 3. 비목표 (Non-goals)

아래는 **현 단계에서 하지 않는다**. 요청이 들어와도 별도 결정 없이 손대지 않는다.

- TLS MITM / 시스템 인증서 조작 — `ANTHROPIC_BASE_URL`로 충분.
- 공개 배포용 설치 마법사, 자동 업데이트.
- Claude Code 외 에이전트의 실제 구현(어댑터 인터페이스만 열어둠).
- 모델이 만든 응답의 토큰 단위 rewrite. 작업 범위 강제로 차단할 때는 합성 응답
  한 덩어리로 대체하지만, 모델이 생성한 토큰을 부분 수정하지는 않는다.
- 자체 ML 기반 이상 탐지 모델 학습.

## 4. 사용자 플로우

```
사용자: llm-tracker start --task <task-id>          (선등록된 작업 컨텍스트로 기동)
사용자: 터미널에서 claude 실행
  └─ Claude Code 프로세스: ANTHROPIC_BASE_URL=http://127.0.0.1:8787
      └─ HTTP POST /v1/messages → 로컬 프록시
          ├─ 요청 기록
          ├─ ▶ Scope guard: 요청 바디의 신규 user 메시지를 등록된 TaskDefinition에
          │     비추어 판정 (in_scope | out_of_scope | uncertain)
          │     ├─ in_scope            → 그대로 진행
          │     ├─ uncertain & strict  → 차단(아래 out_of_scope와 동일)
          │     └─ out_of_scope        → 업스트림 호출 스킵 + 합성 SSE 응답으로
          │                              "범위 밖 요청이라 차단됐다" 통지
          ├─ api.anthropic.com 으로 그대로 포워드 (in_scope일 때만)
          │    └─ SSE 응답 스트림
          ├─ 응답을 tee
          │    ├─ 사용자 클라이언트로 즉시 전달 (지연 없이)
          │    └─ 이벤트 추출 → 스크러빙 → SQLite 버퍼
          └─ (후순위) 응답 측 정책 엔진이 tee 사본을 실시간 평가, 필요시 abort
      └─ 업로더 데몬: SQLite(exchanges + scope_verdicts 등) → 중앙 Ingest API (배치)
```

## 5. 아키텍처

### 5.1 컴포넌트 다이어그램(논리)

```
┌─────────────────────────┐
│ Claude Code (client)    │
└─────────┬───────────────┘
          │ HTTPS (로컬에선 HTTP 가능)
          ▼
┌─────────────────────────────────────────────────────────┐
│                Local Proxy (FastAPI + httpx)            │
│                                                         │
│   ┌──────────┐   ┌──────────┐   ┌──────────────────┐   │
│   │ Router   │──▶│ Forwarder│──▶│ Upstream (httpx) │──▶ api.anthropic.com
│   └──────────┘   └────┬─────┘   └──────────────────┘   │
│                       │                                 │
│                       ▼  (stream tee)                   │
│                 ┌───────────┐                           │
│                 │ Extractor │─┐                         │
│                 └───────────┘ │                         │
│                               ▼                         │
│                         ┌───────────┐                   │
│                         │ Scrubber  │                   │
│                         └─────┬─────┘                   │
│                               ▼                         │
│                         ┌───────────┐                   │
│                         │ Local DB  │  (SQLite, WAL)    │
│                         │  buffer   │                   │
│                         └─────┬─────┘                   │
│                               │                         │
│      (Phase 2) ┌──────────────┴──────────┐              │
│                ▼                         │              │
│           ┌─────────┐                    │              │
│           │ Policy  │──▶ abort/notify    │              │
│           │ engine  │    (upstream로 취소)│              │
│           └─────────┘                    │              │
└───────────────────────────────────────────┼─────────────┘
                                            │
                                            ▼
                                    ┌──────────────┐
                                    │  Uploader    │  (배치, 지수 백오프)
                                    └──────┬───────┘
                                           ▼
                                    ┌──────────────┐
                                    │ Central      │
                                    │ Server (API) │
                                    └──────┬───────┘
                                           ▼
                             ┌─────────────────────────────┐
                             │ Phase 1: Postgres only      │
                             │ Phase 2+: + ClickHouse +    │
                             │           Object store      │
                             │ (자세한 건 §11)              │
                             └─────────────────────────────┘
```

### 5.2 컴포넌트 책임

**Router**. FastAPI의 catch-all 라우트로 Anthropic의 모든 경로(`/v1/messages`, 필요시
`/v1/messages/count_tokens` 등)를 받아 그대로 전달. 인증 헤더는 투명 패스스루.

**Scope guard**. 신규 사용자 메시지가 등록된 작업 정의(`TaskDefinition`)에 비추어
범위 안인지 판정. 판정기는 (a) 빠른 휴리스틱(키워드/임베딩 코사인) → 필요 시 (b)
LLM judge(저렴한 모델 호출)의 2단 구조. `out_of_scope` 판정이 나면 업스트림 호출을
스킵하고 합성 SSE 응답으로 사용자 클라이언트에 차단을 통지. 자세한 설계는 §5.4와
ADR-0002.

**Forwarder**. `httpx.AsyncClient.stream()`으로 업스트림 호출. 응답 바디를 바이트
단위로 받아 `PassThrough` 같은 asyncio 큐로 tee. 사용자 클라이언트 방향 전송은
**지연 없이** 계속. 업스트림 연결은 요청별로 격리.

**Extractor**. SSE 라인(`event:`, `data:`) 파서. Anthropic Messages API의 이벤트
타입을 구조화한다: `message_start`, `content_block_start/delta/stop`, `tool_use`,
`tool_result`(요청 방향), `message_delta`, `message_stop`. 누적하여 "한 HTTP 호출 =
한 exchange 레코드" 형태로 만든다.

**Scrubber**. 수집 레벨 3단계:
- L0 (metadata only): 토큰 카운트, 모델 ID, 지연시간, 툴 이름, 상태 코드.
- L1 (hashed content): 프롬프트/응답을 내용 해시와 토큰 길이만.
- L2 (full content, opt-in): 스크러빙된 원문. 시크릿 정규식·절대경로·이메일·IP 등 제거.

기본값은 L1. L2는 연구 참여자가 명시적 opt-in 했을 때만.

**Local DB buffer**. SQLite(WAL 모드)로 오프라인 내성 확보. 스키마는 §6.

**Uploader**. 별도 태스크. 일정 간격 or 배치 크기 도달 시 중앙 Ingest API로 업로드.
업로드 성공한 레코드만 소프트 삭제. 실패는 지수 백오프.

**Policy engine (Phase 2)**. 룰 DSL은 나중. 초기는 파이썬 함수 기반 훅. 이벤트가
들어올 때마다 동기적으로 호출되어 `CONTINUE | ABORT | NOTIFY` 중 하나를 반환.
`ABORT`면 업스트림 요청을 취소하고, 사용자 방향 스트림에 합성 `message_stop`을 끼워
넣어 Claude Code가 깔끔히 끝내게 한다.

### 5.3 어댑터 추상화

현재는 Claude Code만 구현하지만, 제공자 추가를 위해 아래 인터페이스를 둔다.

```python
class ProviderAdapter(Protocol):
    name: str                          # "anthropic", "openai", ...
    def match(self, request) -> bool: ...
    def parse_request(self, raw) -> RequestRecord: ...
    def parse_response_stream(self, stream) -> AsyncIterator[Event]: ...
    def upstream_url(self, request) -> str: ...
```

어댑터는 `llm_tracker.adapters.anthropic`에 하나만 존재. OpenAI/Gemini용은 스텁도
만들지 않는다(후순위).

### 5.4 Task-scope guard 상세 설계

세 가지 결정해야 할 부분: (1) 작업 정보를 어떻게 입력받는가, (2) 무관함을 어떻게
판정하는가, (3) 차단 응답을 어떻게 구성하는가. 결정은 ADR-0002에 잠정 봉인되어 있고
여기엔 동작 사양만 적는다.

**(1) 작업 정의의 입력 — `TaskDefinition`**

작업 정의는 사용자가 자유로이 적는 게 아니라, **중앙에서 발급되어 로컬로 동기화**된다.
연구·기업 환경 모두 "관리자가 정의 → 사용자는 적용"이 자연스럽다. 사용자가 자기
스코프를 임의로 늘리지 못하게 하려면 출처가 통제돼야 한다.

```yaml
# 예시: research-claude-drift-2026.yaml (중앙 발급)
id: research-claude-drift-2026
name: "Claude drift 추적 연구"
description: |
  Claude 모델의 시간에 따른 변화를 측정하기 위한 표준 질문/태스크 수행.
  코드 디버깅, 알고리즘 구현, 문서 작성 등 일반 SWE 업무 시뮬레이션을 포함한다.
positive_examples:
  - "이 파이썬 함수의 버그를 찾아줘"
  - "binary search 구현해줘"
  - "이 README를 영어로 번역"
negative_examples:
  - "내일 부산 여행 일정 짜줘"
  - "내 친구 생일 축하 카드 문구 만들어줘"
  - "주식 종목 추천해줘"
judge_strategy: hybrid       # embedding | llm_judge | hybrid
strict_mode: true            # uncertain일 때 차단 여부
judge_model: claude-haiku-4-5
```

로컬은 이 파일을 SQLite의 `task_definitions`에 캐시. 중앙 발급 정의의 해시가 바뀌면
재동기화. 사용자 머신에서 직접 편집한 변경은 무시(서명/체크섬 검증).

**(2) 무관함 판정 — 2단 judge**

요청이 들어올 때마다 LLM 호출을 추가하면 first-token-latency가 망가진다. 그래서
2단 구조를 쓴다.

1. **Stage 1 (cheap)**: 정의의 description + positive/negative examples를 사전
   임베딩해 둔다. 들어온 user 메시지를 임베딩하여 positive 평균 / negative 평균과의
   코사인 유사도를 계산. 임계값 이상으로 in/out 결정. 결정 신뢰도가 낮으면(둘 다
   비슷) Stage 2로 에스컬레이트.
   - 임베딩 모델은 로컬(예: sentence-transformers small)이어야 한다. 외부 호출
     추가는 곤란.
2. **Stage 2 (LLM judge)**: 저렴한 모델(예: Claude Haiku)로 system prompt:
   `"You judge whether USER_MSG falls within TASK_DEFINITION. Reply only JSON
   {verdict: in_scope|out_of_scope|uncertain, reason}."`
   응답을 파싱해 결정.

**무엇을 judge에 입력하는가** (중요): user가 새로 보낸 메시지만 평가한다. 대화 컨텍스트
전체를 평가하면 (a) 비용이 크고 (b) 이전에 통과한 toolresult/모델 출력이 잘못 영향을
준다. Anthropic Messages API의 `messages` 배열에서 마지막 `role: "user"`의 텍스트
content만 추려 입력.

**캐시**: `(task_id, message_hash)` → verdict LRU 캐시(메모리 + SQLite). 같은 사용자가
같은 메시지를 두 번 보내면 (Claude Code의 retry 등) 재판정 안 함.

**Tool result는 평가하지 않는다**: tool_result로 들어오는 파일 내용 등은 사용자 의도를
나타내지 않는다. user 메시지(`role: user`이고 content에 `tool_result`가 아닌 `text`가
있는 경우)만 평가 대상.

**(3) 차단 응답의 구성**

업스트림 호출을 안 했으므로 응답을 우리가 합성해야 한다. Claude Code는 SSE를 기대하므로
synthetic stream을 만들어 보낸다.

```text
event: message_start
data: {"type":"message_start","message":{"id":"msg_blocked_<ulid>","type":"message",
       "role":"assistant","model":"<requested-model>","content":[],
       "stop_reason":null,"usage":{"input_tokens":0,"output_tokens":0}}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,
       "delta":{"type":"text_delta","text":"[llm-tracker] 이 요청은 등록된 작업 범위(<task-name>) 밖이라 자동 차단되었습니다.\n사유: <reason>\n작업 범위 내 요청으로 다시 시도해주세요."}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":<n>}}

event: message_stop
data: {"type":"message_stop"}
```

핵심은 Claude Code 파서가 받아들이는 정확한 형태로 만들어야 한다는 것. `tool_use`는
넣지 않는다(툴을 실행시키면 안 됨).

**옵션: 사용자 통지 채널**. 합성 응답 텍스트에 사유를 넣는 것 외에 별도 OS 노티/터미널
벨을 울릴 수 있다. Phase 2 기본은 텍스트만, 추가 채널은 후순위.

**Override 정책**. 초기엔 사용자측 override를 두지 않는다. False positive가 누적되면
관리자가 task definition을 갱신하는 것이 정상 경로. CLI 플래그로 한 회 우회를
허용하면 강제력이 사라진다. 단, **모든 차단을 `scope_verdicts`에 기록**하므로 후행
분석으로 false positive를 식별·수정할 수 있다.

## 6. 데이터 모델

### 6.1 로컬 SQLite 테이블(초안)

```sql
CREATE TABLE exchanges (
  id              TEXT PRIMARY KEY,        -- ULID
  session_id      TEXT NOT NULL,           -- Claude Code 대화 추적 키
  started_at      INTEGER NOT NULL,        -- epoch ms
  ended_at        INTEGER,
  provider        TEXT NOT NULL,           -- "anthropic"
  endpoint        TEXT NOT NULL,           -- "/v1/messages"
  model_requested TEXT,                    -- req.model
  model_served    TEXT,                    -- response의 실제 model (drift 추적 핵심)
  status_code     INTEGER,
  input_tokens    INTEGER,
  output_tokens   INTEGER,
  cache_read_tokens  INTEGER,
  cache_write_tokens INTEGER,
  latency_ms      INTEGER,
  stop_reason     TEXT,
  tool_call_count INTEGER DEFAULT 0,
  content_level   TEXT NOT NULL,           -- L0 | L1 | L2
  upload_state    TEXT NOT NULL DEFAULT 'pending'  -- pending | uploaded | failed
);

CREATE TABLE events (                      -- SSE 이벤트 단위의 세부 기록
  id           TEXT PRIMARY KEY,           -- ULID
  exchange_id  TEXT NOT NULL REFERENCES exchanges(id),
  seq          INTEGER NOT NULL,
  ts           INTEGER NOT NULL,           -- epoch ms
  kind         TEXT NOT NULL,              -- message_start | content_delta | tool_use | ...
  payload_json TEXT                        -- 스크러빙된 json
);

CREATE TABLE tool_calls (
  id           TEXT PRIMARY KEY,
  exchange_id  TEXT NOT NULL REFERENCES exchanges(id),
  name         TEXT NOT NULL,              -- Bash | Read | Edit | ...
  input_hash   TEXT,
  input_json   TEXT,                       -- L2일 때만 채움
  result_hash  TEXT,
  result_json  TEXT
);

CREATE TABLE task_definitions (    -- 중앙 발급, 로컬에 캐시
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  description     TEXT NOT NULL,
  positive_examples_json TEXT,     -- 범위 안 예시
  negative_examples_json TEXT,
  judge_strategy  TEXT NOT NULL,   -- embedding | llm_judge | hybrid
  judge_model     TEXT,            -- LLM judge 모델 (Stage 2)
  strict_mode     INTEGER NOT NULL,-- 0/1: uncertain일 때 차단 여부
  signature       TEXT,            -- 중앙 서명/체크섬 (변조 검증용)
  fetched_at      INTEGER NOT NULL,
  active          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE scope_verdicts (
  id           TEXT PRIMARY KEY,
  exchange_id  TEXT NOT NULL REFERENCES exchanges(id),
  task_id      TEXT NOT NULL REFERENCES task_definitions(id),
  verdict      TEXT NOT NULL,      -- in_scope | out_of_scope | uncertain
  confidence   REAL,
  reasoning    TEXT,               -- judge가 남긴 사유
  judge_kind   TEXT NOT NULL,      -- embedding | llm_judge | cache
  judge_latency_ms INTEGER,
  user_message_hash TEXT NOT NULL, -- 캐시 키 (sha256 of normalized text)
  decided_at   INTEGER NOT NULL
);

CREATE INDEX idx_exchanges_started ON exchanges(started_at);
CREATE INDEX idx_exchanges_upload  ON exchanges(upload_state);
CREATE INDEX idx_events_exchange   ON events(exchange_id, seq);
CREATE INDEX idx_verdicts_exchange ON scope_verdicts(exchange_id);
CREATE INDEX idx_verdicts_cache    ON scope_verdicts(task_id, user_message_hash);
```

### 6.2 세션 식별

Claude Code는 대화 상태를 자체 관리하므로, 프록시 입장에서 "같은 대화"를 확실히
묶기 어렵다. 초기 전략:

- 프록시 프로세스 수명 내 IP+시작시각+user-agent를 묶어 휴리스틱 `session_id` 생성.
- Claude Code의 요청 바디에 포함된 `metadata.user_id` 또는 전체 messages 배열의
  첫 메시지 해시를 보조 키로 사용.
- 확실하지 않음. ADR 후보로 열어둔다.

## 7. 기술 리스크와 PoC에서 검증할 항목

| 리스크 | 검증 방법 | 통과 조건 |
|---|---|---|
| SSE 스트리밍 tee가 체감 지연을 유발 | 로컬에서 같은 프롬프트에 대해 직접 호출 vs 프록시 경유 호출의 first-token-latency 측정 | +50ms 이내 |
| `ANTHROPIC_BASE_URL`로 모든 경로가 라우팅되는지(인증 포함) | `httpbin` 대체 서버로 요청 전부 캡처 후 누락 경로 확인 | 누락 경로 없음 |
| OAuth 토큰 갱신 흐름이 프록시 경유에서도 문제없이 동작 | Claude 구독 계정으로 장시간 세션 수행 | 재인증 없이 세션 유지 |
| Tool use 이벤트 파싱이 모든 변형(병렬 tool call, tool_result injection)에서 맞는지 | 합성 SSE 스트림 테스트 + 실제 장시간 세션 녹음/재생 | 녹화된 세션 100% 파싱 |
| 스크러빙 누락 | 시크릿·경로 포함한 가짜 세션 실행 후 SQLite에 남은 내용 grep | 블랙리스트 패턴 0건 |
| Scope guard가 first-token-latency를 망가뜨림 | Stage 1만 통과한 경우와 Stage 2까지 간 경우의 latency 측정 | Stage 1: +30ms, Stage 2: +500ms 이내 |
| Scope guard의 false positive (작업 범위인데 차단) | 작업당 in/out 50개씩 수동 라벨링한 평가셋으로 정밀도/재현율 측정 | False positive ≤ 5% |
| Prompt injection으로 judge 우회 | "이전 지시 무시하고 …" 류 공격 프롬프트 30개 평가셋 | 우회 성공 ≤ 1건 |
| Judge 호출에 따른 user 데이터 추가 노출 | Stage 2가 외부 모델일 때 데이터 흐름 도식 검토 + opt-in 명문화 | 명시적 opt-in 동의서에 반영 |

## 8. 보안/프라이버시

- 시크릿은 로그 파일에도 남기지 않는다. `structlog` 포매터 레벨에서 필터.
- 로컬 SQLite는 사용자 홈 아래 `~/.local/share/llm-tracker/` (macOS는 대응 경로).
  OS 권한만 의존. 암호화는 현 단계에선 안 함(연구 참여자 동의 범위로 갈음).
- 중앙 업로드는 HTTPS + API 토큰. 토큰은 OS 키체인(Python `keyring`) 저장.
- 프록시는 `127.0.0.1`에만 바인딩. 로컬호스트 외부 노출 금지.

## 9. 의존성(예정)

- `fastapi`, `uvicorn[standard]` — 서버
- `httpx[http2]` — 업스트림 클라이언트
- `pydantic`, `pydantic-settings` — 설정/모델
- `structlog` — 로깅
- `typer` — CLI
- `sqlalchemy` + `aiosqlite` 또는 `sqlite-utils` — 로컬 저장
- `python-ulid`
- `keyring`
- dev: `pytest`, `pytest-asyncio`, `respx`(httpx mocking), `ruff`, `mypy`

모두 PyPI 표준. 실제 고정은 `pyproject.toml`에서.

## 10. 오픈 이슈

- 세션 식별 전략 확정(§6.2).
- Anthropic API ToS와 연구 목적 수집/재사용의 합법성 검토(법무 자문 필요).
- 중앙 서버 스택과 코드 위치는 ADR-0004에서 봉인됨 (Supabase + Fly.io + 동일 레포).
- 연구 참여자 동의서 흐름(UX, 저장 기간, 삭제 요청 프로세스).
- Stage 2 judge 모델 확정(Claude Haiku vs 로컬 모델). 비용·프라이버시 트레이드오프.
- 연속 차단 시 사용자 경험(Claude Code가 무한 retry할 가능성 검토).
- 배포·업데이트 전략 — `docs/distribution.md` 분석 후 ADR-0003에서 봉인.

## 11. 중앙 서버와 전체 데이터 흐름 (잠정 안)

### 11.1 중앙이 담당하는 역할

1. **Ingest** — 로컬 프록시들에서 올라오는 스크러빙된 exchange 레코드 수신·저장.
2. **Rule distribution** — TaskDefinition·차단 메시지 템플릿·스크럽 정책을 로컬에
   배포. 변조 방지를 위해 서명.
3. **Enrollment / Auth** — 연구 참여자 등록, API 토큰 발급.
4. **Analytics 인터페이스** — 지표 담당자가 drift 분석 쿼리를 돌릴 수 있는 SQL
   엔드포인트 또는 read-only DB 접근.
5. **Admin UI** (후순위) — task 정의 관리, false positive 검토.

### 11.2 데모 스택 (확정: Supabase + Fly.io)

ADR-0004로 봉인됨. 데모는 무료 한도 안에서 외부에서 접근 가능한 형태로 운영한다.

- **DB**: **Supabase** Postgres 무료 한도. 단, **표준 Postgres 프로토콜만** 사용한다
  (RLS 자동·RPC·Edge Function·Storage·Realtime 등 Supabase 전용 기능 사용 금지).
  이렇게 두면 self-host Postgres / Neon / RDS로 이전이 환경변수 한 줄로 끝난다.
- **앱**: **Fly.io** 무료 한도. Dockerfile 푸시로 배포. Persistent VM(콜드스타트 없음).
- **TLS**: Fly.io 기본 제공 (커스텀 도메인은 Phase 1 후반 결정).
- **TaskDefinition 서명 키**: 운영자 머신에 보관, Fly.io secret으로 주입. 공개키만
  코드에 임베딩(클라이언트 검증용).

**코드 위치**: 동일 레포 `src/llm_tracker_server/`. 자세한 디렉토리는 §11.8.

**Phase 1 후반(production)**: §11.3 트리거에 따라 self-host VM(Hetzner ~€4/월) +
Postgres 매니지드 백업. ClickHouse·MinIO 도입은 그 다음. Supabase에서 self-host로
이전은 `pg_dump` 한 번 + `DATABASE_URL` 변경.

### 11.3 확장 트리거 (Phase 2 이후 도입)

| 트리거 조건 | 추가 도입 |
|---|---|
| `events` 테이블이 ~1000만 row 넘기거나 분석 쿼리가 분 단위로 늦어짐 | ClickHouse(또는 TimescaleDB). 분석 데이터만 옮기고, OLTP는 Postgres에 둔다. |
| L2(opt-in) 원본 본문 누적 ≥ 50 GB | MinIO(자체 호스팅 S3) 또는 클라우드 S3로 이전. Postgres엔 객체 키만 남김. |
| 동시 활성 프록시 ≥ 50 | 앱 인스턴스 수평 확장 + Postgres pgbouncer + 별도 redis(idempotency 키, 캐시) |

이걸 미리 설계에 반영하기 위해 분석 데이터 스키마는 표준 SQL 위주로 작성한다
(Postgres 전용 확장 자제 → ClickHouse 마이그레이션 비용 작음).

### 11.4 사이징 추정 (연구 50명 가정)

- 활성 사용자: 50명
- 활성 사용자당 평균 100 exchanges/day
- L0/L1 메타데이터: 한 exchange당 ~10 KB → 50 × 100 × 10 KB = 50 MB/day → ~18 GB/year
- L2(opt-in) 원본 본문: 한 exchange당 평균 50 KB(편차 큼) → opt-in 비율 30% 가정 시
  50 × 100 × 50 KB × 0.3 = 75 MB/day → ~27 GB/year
- 합계: 첫 해 ~50 GB. 200 GB SSD로 여유 있음. 백업까지 고려해도 1년은 단일 VM으로 가능.

### 11.5 인증·서명

- 로컬 프록시 ↔ 중앙 통신: HTTPS + 사용자별 API 토큰 (등록 시 발급).
- 토큰 저장: 로컬은 OS 키체인(`keyring`).
- TaskDefinition: 중앙의 ed25519 서명 키로 서명. 클라이언트는 임베딩된 공개키로 검증.
  서명이 깨지거나 만료되면 task 적용 거부 → 프록시는 시작 거부.
- Ingest 페이로드: API 토큰만으로 충분(전송 무결성은 TLS가 보장). 단, 클라이언트 측
  타임스탬프와 서버 시각이 너무 차이 나면 거부(replay 방지).

### 11.6 전체 데이터 흐름 (end-to-end)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ User machine                                                            │
│                                                                         │
│   ┌────────┐   "fix this bug"                                           │
│   │ User   │──────────────┐                                             │
│   └────────┘              ▼                                             │
│                     ┌──────────────┐                                    │
│                     │ Claude Code  │                                    │
│                     │ (CLI)        │                                    │
│                     └──────┬───────┘                                    │
│                            │ HTTP POST /v1/messages                     │
│                            │ ANTHROPIC_BASE_URL=http://127.0.0.1:8787   │
│                            ▼                                            │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │ Local Proxy  (FastAPI :8787)                                   │   │
│   │                                                                │   │
│   │  ① Scope Guard                                                 │   │
│   │     ├─ Stage 1 임베딩 코사인 (~30ms)                            │   │
│   │     └─ Stage 2 LLM judge (~500ms, 필요시만)                    │   │
│   │     ↓                                                          │   │
│   │     [out_of_scope] → ⑥ 합성 차단 응답                           │   │
│   │     [in_scope]     → ② 진행                                     │   │
│   │                                                                │   │
│   │  ② Forwarder (httpx async stream)  ──────────────────────────────────┐
│   │     ▲                                                          │   │ │
│   │     │  업스트림 SSE 스트림                                       │   │ │
│   │  ③ Tee                                                         │   │ │
│   │     ├─→ 사용자 클라이언트로 즉시 전달 (Claude Code가 토큰 표시)  │   │ │
│   │     └─→ Extractor → Scrubber                                   │   │ │
│   │                          │                                     │   │ │
│   │                          ▼                                     │   │ │
│   │  ④ Local SQLite buffer  (~/.local/share/llm-tracker/buffer.sqlite) │ │
│   │     · exchanges                                                │   │ │
│   │     · events                                                   │   │ │
│   │     · tool_calls                                               │   │ │
│   │     · scope_verdicts                                           │   │ │
│   │     · task_definitions (cache)                                 │   │ │
│   │                          │                                     │   │ │
│   │                          ▼                                     │   │ │
│   │  ⑤ Uploader (배치, 지수 백오프)                                  │   │ │
│   │     · upload_state=pending → POST /v1/ingest                   │   │ │
│   │     · 성공 → uploaded                                           │   │ │
│   └─────────────────────────┬──────────────────────────────────────┘   │ │
│                             │ HTTPS + API token                         │ │
└─────────────────────────────┼─────────────────────────────────────────────┘
                              │                                            │
                              ▼                                            ▼
┌──────────────────────────────────────────────────┐            ┌───────────────────┐
│ Central Server (single VM, Phase 1)              │            │ api.anthropic.com │
│                                                  │            │ (업스트림 LLM)     │
│   ┌─────────────────────────────────────────┐    │            └───────────────────┘
│   │ llm-tracker-server  (FastAPI)           │    │
│   │                                         │    │
│   │  POST /v1/enroll       ← 등록            │    │
│   │  GET  /v1/tasks/{id}   → TaskDefinition │────┼─── 로컬 프록시 룰 동기화 (서명된 응답)
│   │  POST /v1/ingest       ← exchange 업로드│    │
│   │  GET  /v1/version      → 클라이언트 버전 │    │
│   │  GET  /v1/analytics/...→ 지표 담당자용  │    │
│   └─────────────────────┬───────────────────┘    │
│                         │                        │
│                         ▼                        │
│   ┌─────────────────────────────────────────┐    │
│   │ PostgreSQL 16 (단일 인스턴스)             │    │
│   │   OLTP 영역                              │    │
│   │    · users                              │    │
│   │    · enrollments / api_tokens           │    │
│   │    · task_definitions (canonical)       │    │
│   │    · signing_keys                       │    │
│   │   분석 영역 (Phase 1엔 같이)              │    │
│   │    · exchanges                          │    │
│   │    · events                             │    │
│   │    · tool_calls                         │    │
│   │    · scope_verdicts                     │    │
│   └─────────────────────────────────────────┘    │
│                         ▲                        │
│                         │ read-only SQL or API   │
│   ┌─────────────────────┴───────────────────┐    │
│   │ Analyst (지표 담당자) / Admin UI         │    │
│   │ — drift 쿼리, false positive 검토        │    │
│   └─────────────────────────────────────────┘    │
│                                                  │
│   [Phase 2 이후 추가 가능]                         │
│   · ClickHouse  (events / exchanges 분석 가속)   │
│   · MinIO/S3    (L2 원본 본문 blob)              │
└──────────────────────────────────────────────────┘
```

### 11.7 데이터 흐름의 시간축

같은 일이 시간 순으로 어떻게 일어나는지 풀어 적은 버전.

1. **t=0**: 사용자가 `claude`에서 프롬프트 입력. Claude Code가 `/v1/messages` POST.
2. **t≈0–30ms**: 로컬 프록시 Router가 받음 → user 메시지 추출 → Stage 1 임베딩 judge.
3. **t≈30–500ms** (필요시만): Stage 2 LLM judge 호출.
4. **분기**:
   - `out_of_scope`: 업스트림 호출 안 하고 합성 SSE 응답 즉시 전송. exchanges 테이블에
     `status="blocked"`, scope_verdicts에 verdict 기록. 끝.
   - `in_scope`: 업스트림 `api.anthropic.com`으로 헤더+바디 그대로 포워드.
5. **t≈수초**: 업스트림이 SSE 토큰을 흘리기 시작. Forwarder는 이를 두 갈래로:
   - 사용자 방향: 그대로 흘림(지연 없음).
   - 내부 방향: Extractor → Scrubber → SQLite append.
6. **t=stream end**: `message_stop` 이벤트. exchanges row의 `ended_at`/`output_tokens`/
   `stop_reason` 등 finalize.
7. **t+α (백그라운드)**: Uploader 데몬이 `upload_state='pending'` 행을 모아 중앙
   `/v1/ingest`에 POST. 응답 200이면 `uploaded`로 마크.
8. **별개 채널 (백그라운드, 주기적)**: 로컬 프록시가 `/v1/tasks/{id}` 폴링으로
   TaskDefinition 갱신 여부 체크. 새 정의 있으면 서명 검증 후 캐시 갱신.
9. **별개 채널 (분석)**: 지표 담당자가 중앙 Postgres에 read-only로 접근하여 SQL 쿼리
   또는 `/v1/analytics/...` 호출.

### 11.8 Migration-friendly 코드 구조

지금 Postgres → 나중에 self-host / ClickHouse / MinIO로 갈아끼울 때 코드 변경이
작도록 세 원칙.

**원칙 1 — 레이어 분리 (가장 중요)**

- `api/`는 HTTP 모양만 안다. DB 모름.
- `domain/`은 비즈니스 로직만. SQLAlchemy import 금지.
- `storage/`만 DB 접근. 외부에 expose하는 건 repository 인터페이스.
- `analytics/`는 분석 쿼리 전용. 나중에 ClickHouse로 갈아낄 때 이 모듈만 교체.

**원칙 2 — vendor-specific 기능 자제**

- 표준 SQL 위주. JSONB는 OK(Neon/Supabase/RDS 모두 지원).
- Supabase RPC, Neon Edge Function, Postgres 14+ 전용 문법 등 호스팅 잠금 요소 금지.
- 연결은 `DATABASE_URL` 환경변수 하나. 12-factor.

**원칙 3 — 마이그레이션은 Alembic**

- 스키마 변경은 모두 `alembic revision`. 어떤 호스팅에도 동일 적용.
- 매뉴얼 SQL 변경 금지(supabase 콘솔에서 칼럼 추가 같은 거).

**권장 디렉토리 구조** (`server/` 하위 또는 별도 패키지로):

```
src/llm_tracker_server/
├── main.py                  # FastAPI 앱, 라우트 마운트, 의존성 주입 wiring
├── config.py                # pydantic-settings (DATABASE_URL, SIGNING_KEY 등)
├── api/                     # HTTP 레이어 — 얇게, 검증 + service 호출만
│   ├── ingest.py
│   ├── tasks.py
│   ├── enroll.py
│   ├── version.py
│   └── analytics.py
├── domain/                  # 순수 비즈니스 로직, IO 모름
│   ├── models.py            # Pydantic 모델 (전송·DB와 무관)
│   └── services.py          # use case 함수 (ingest_exchange, issue_task_def, ...)
├── storage/                 # DB 접근 단일 진입점
│   ├── db.py                # async engine, session 팩토리
│   ├── schema.py            # SQLAlchemy 2.0 declarative
│   ├── repositories/
│   │   ├── users.py         # class UserRepository: create, get, ...
│   │   ├── tasks.py
│   │   ├── exchanges.py
│   │   ├── events.py
│   │   └── verdicts.py
│   └── migrations/          # Alembic versions/ + env.py
├── analytics/               # 읽기 전용 쿼리 (ClickHouse 후보)
│   ├── interface.py         # AnalyticsBackend 추상
│   ├── postgres_backend.py  # 현재 구현
│   └── drift_queries.py     # 지표 쿼리 모음
└── signing/                 # ed25519 서명 헬퍼 (TaskDefinition 서명용)
```

**시나리오별 영향 범위** (구조가 잘 지켜지면):

| 시나리오 | 변경 범위 |
|---|---|
| Neon → self-host Postgres | `DATABASE_URL` 환경변수만. 코드 무수정. |
| Neon → Supabase | 같음. (둘 다 일반 Postgres 프로토콜) |
| 분석을 Postgres → ClickHouse | `analytics/clickhouse_backend.py` 추가, `interface.py` 라우팅 플래그. ingest path 무영향. |
| L2 본문을 Postgres → MinIO/S3 | `storage/repositories/exchanges.py`의 본문 컬럼을 객체 키로. `storage/blobs.py` 추가. `domain/services.py`는 객체 ID만 다루도록 살짝 수정. |
| 동시 활성 사용자 폭증 | `main.py`의 의존성 주입에 pgbouncer URL + 캐시 추가. 도메인 코드 무영향. |

### 11.9 무엇이 아직 결정 안 됐나

- 서명 키 회전 정책.
- 분석 인터페이스의 형태(SQL 직접 vs REST). 지표 담당자 작업 스타일에 맞춰 결정.
- Supabase auth를 enrollment에 활용할지(편함, 약간의 vendor 결합) vs 자체 토큰 발급
  (복잡, 이식성 우수). ADR-0004 미해결 항목.

---

## 참고

- 단계별 마일스톤: `docs/roadmap.md`
- 잠정 결정 기록: `docs/decisions/`
- 배포·업데이트 전략 분석: `docs/distribution.md`
- Claude Code가 따라야 할 작업 규칙: `/CLAUDE.md`
