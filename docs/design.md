# 설계 문서 — LLM 트래픽 관측/개입 **프레임워크**

**상태**: Draft v0.2 (2026-05-01, framework pivot)
**오너**: 이민섭
**범위**: Claude Code를 우선 대상으로 한 로컬 사이드카 프록시 **프레임워크**.
구체적 기능(scope 강제, drift 추적, 데이터 업로드, 응답 검사 등)은 모두
**플러그인**으로 구현된다. 본 리포지토리의 코어는 plugin host와 보안 경계를 제공.

---

## 1. 프로젝트 맥락

상위 프로젝트는 LLM 사용 추적·개입을 목표로 하지만, 다음을 인지하면서 본 리포의
역할을 *제품*에서 *프레임워크*로 재정의했다 (ADR-0005).

- **협업자들이 추가 기능을 계속 붙인다.** 코어를 자주 건드리지 않고 새 기능을
  플러그인으로 얹을 수 있어야 한다. 어떤 기능이 들어올지는 아직 상세 정의 전.
- **고객 시나리오에선 데이터를 외부로 보내고 싶지 않을 수 있다.** 회사 업무용
  Claude Code 사용 로그는 극비일 수 있다. 따라서 *데이터 egress는 옵션이고
  명시적 동의 후에만 일어난다*가 본 프레임워크의 기본 가정.
- **연구 시나리오에선 더 풍부한 데이터 수집이 필요할 수 있다.** opt-in 한 사용자에
  한해 우리가 정의한 schema대로 외부로 보내야 한다.

세 시나리오를 같은 프레임워크 위에서 다 지원하려면, 코어는 *기능 없는 호스트*여야
하고, 모든 *행동*은 플러그인으로 격리·통제 가능해야 한다.

지표 설계와 질문 세트 큐레이션은 다른 구성원의 작업이며, 그 결과물은 결국 본
프레임워크 위의 플러그인(예: `drift_metrics`)으로 들어온다.

## 2. 설계 결정 (확정)

| # | 항목 | 결정 | 근거 |
|---|---|---|---|
| 1 | 배포 형태 | 사용자 로컬 사이드카 (프레임워크) | ADR-0001 |
| 2 | 언어 | Python 3.11+, FastAPI, httpx | ADR-0001 |
| 3 | 대상 에이전트 | Claude Code (Anthropic Messages) 우선 | ADR-0001 |
| 4 | 아키텍처 | **프레임워크 + 플러그인** 모델 | **ADR-0005** |
| 5 | 데이터 egress | **기본 OFF**. 플러그인이 capability 받아 명시적으로 수행 | **ADR-0006** |
| 6 | 배포 모드 | L (local-only) / A (audit-light) / R (research) | **ADR-0006** |
| 7 | 중앙 서버 | 기본 컴포넌트 아님. Mode R용 *reference upload sink 플러그인*으로 존재 | **ADR-0007** (ADR-0004 supersede) |

## 3. 비목표

- 모델이 만든 토큰을 단위로 rewrite하는 개입 (영구 비목표).
- 프레임워크 자체가 도메인 *기능*을 보유하는 것 — 모든 행동은 플러그인.
- TLS MITM (`ANTHROPIC_BASE_URL`로 충분).
- Phase 0–1에선 비-Python 플러그인 SDK (WASM/subprocess 격리 등)는 제공하지 않는다.

## 4. 핵심 설계 원칙

본 프레임워크의 모든 결정은 다음 세 원칙을 우선한다. 충돌하면 위에서부터.

**1) 확장성 우선.** 새 기능 추가는 코어 수정 없이 플러그인 패키지 하나 추가로 끝나야
한다. 코어는 hook 점과 capability 어휘만 정의하고, *어떤 기능도* 보유하지 않는다.
"이걸 코어에 넣자"는 거의 항상 잘못된 답.

**2) 보안 우선.** 기본값은 가장 보수적인 쪽. 데이터는 기본적으로 외부로 나가지
않는다. 플러그인이 외부 통신·민감 데이터 접근을 하려면 명시적 capability를 받아야
하고, 모든 사용은 audit log에 남는다. 운영자가 *명시적으로 허용한 적이 없는*
egress는 절대 일어나지 않는다.

**3) 모드 인지.** 프레임워크는 deployment mode(L/A/R)를 알고 있고, 모드에 따라
어떤 capability가 허용되는지를 강제한다. Mode L에선 egress capability 자체가
존재하지 않는다 — 플러그인이 요청해도 거부.

## 5. 사용자/운영자 플로우

### 5.1 운영자 (관리자/PI/사용자 본인)

```
1. llm-tracker init                           # 설정 초기화
2. 모드 선택: L | A | R
3. 플러그인 선택 + 각 플러그인 manifest의 capability 검토·승인
4. llm-tracker start                          # 프록시 가동
5. export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
6. claude (평소처럼 사용)
```

### 5.2 한 요청의 라이프사이클 (high-level)

```
Claude Code → 로컬 프록시
   │
   ▼
[Router] → [PluginHost: on_request_received]      ─┐ 플러그인이 PASS|BLOCK|TRANSFORM 반환
                                                   │ (BLOCK이면 합성 응답 즉시 반환)
   ▼                                               │
[PluginHost: before_forward]                      ─┘
   │
   ▼
[Forwarder] → api.anthropic.com (SSE)
   │
   ▼
[Tee] ─┬─ 사용자 클라이언트로 즉시 전달
       └─ [Extractor] → [Scrubber] → [Local SQLite]
                                       │
                                       ▼
                                 [PluginHost: on_response_chunk]    (스트림 중)
                                 [PluginHost: on_response_complete] (스트림 끝)
                                 [PluginHost: on_persisted]         (저장 후)
```

플러그인은 자기가 등록한 hook에서만 호출되고, 그 hook이 허용하는 capability 범위
내에서만 동작한다.

## 6. 프레임워크 아키텍처

### 6.1 코어 컴포넌트

```
┌─────────────────────────────────────────────────────────────────────┐
│ llm_tracker (core)                                                  │
│                                                                     │
│  ┌─────────┐   ┌──────────────┐   ┌─────────────┐                   │
│  │ Router  │──▶│ Plugin Host  │──▶│ Forwarder   │──▶ api.anthropic │
│  └─────────┘   │  (hooks +    │   └──────┬──────┘                   │
│                │  capability) │          │                          │
│                └──────┬───────┘          │ SSE                      │
│                       │                  ▼                          │
│                       │             ┌────────┐                      │
│                       │             │  Tee   │──▶ 사용자 클라이언트   │
│                       │             └───┬────┘                      │
│                       │                 ▼                           │
│                       │           ┌──────────┐                      │
│                       └──────────▶│Extractor │                      │
│                                   └────┬─────┘                      │
│                                        ▼                            │
│                                   ┌──────────┐    ┌──────────────┐  │
│                                   │ Scrubber │───▶│ Local SQLite │  │
│                                   └──────────┘    └──────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  EgressGuard ── 모든 외부 HTTP 단일 경로. allowlist 강제      │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  AuditLog ── hook 호출, capability 사용, egress 시도, 모든    │   │
│  │              plugin lifecycle 이벤트 별도 테이블에 기록       │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 코어 컴포넌트 책임

**Router**. FastAPI catch-all로 Anthropic 모든 경로를 받음. 인증 헤더 패스스루.

**Plugin Host**. 등록된 플러그인을 모드 정책·capability에 따라 로드. 요청 라이프사이클의
8개 hook 지점에서 등록 플러그인을 dispatch. 각 hook은 정해진 capability 안에서만
동작; 위반 시 plugin은 거부되거나 격리.

**Forwarder**. `httpx.AsyncClient.stream()`으로 업스트림 호출. 스트림은 Tee로 분기.

**Tee**. 응답 SSE를 두 갈래로. 사용자 방향엔 지연 없이, 내부엔 Extractor·hook용.

**Extractor**. SSE 이벤트(`message_start`, `content_block_*`, `tool_use`, `message_delta`,
`message_stop`)를 구조화된 레코드로 누적.

**Scrubber**. 콘텐츠 레벨(§7.1)에 따라 시크릿/PII/경로/이메일/IP를 제거·해시. **Plugin이
데이터를 보기 전에** 적용 — 미민감 plugin이 raw 데이터에 닿지 못하게 함.

**Local SQLite**. 코어 테이블(§9.1) + 플러그인이 자기 namespace에 생성한 보조 테이블.

**EgressGuard**. *모든* 외부 HTTP의 단일 경로. 플러그인이 외부로 나가려면 EgressGuard에
요청해야 하며, EgressGuard는 (a) 플러그인이 `egress_http` capability를 갖는지, (b) 대상
URL이 plugin manifest의 allowlist에 있는지, (c) 현재 모드에서 그 capability가
허용되는지 검사 후 forward. 모든 시도는 AuditLog에 기록.

**AuditLog**. 위 모든 사건을 별도 테이블(또는 별도 DB)에 append-only로 기록. 운영자
검토용.

### 6.3 플러그인 호스트 모델

#### 6.3.1 Plugin manifest

플러그인은 Python 패키지이며 setuptools entry point(`llm_tracker.plugins`)로 자기를
등록. 각 플러그인은 `plugin.toml` manifest를 가진다.

```toml
# 예시: plugin.toml
name = "scope_guard"
version = "0.1.0"
description = "Block requests outside the declared task scope."

# 어떤 hook들에 binding 하는지
hooks = ["before_forward", "on_persisted"]

# 필요로 하는 capability 목록 (운영자가 명시 승인해야 함)
capabilities = [
  "read_request_content",     # user 메시지를 읽어야 함
  "block_request",            # 합성 차단 응답을 낼 수 있어야 함
  "egress_http",              # Stage 2 LLM judge 호출 (선택; 로컬 judge면 불필요)
]

# 외부 통신을 한다면 destination allowlist
egress_destinations = ["https://api.anthropic.com"]   # Haiku judge 호출용

# 어떤 모드에서 동작 가능한가
allowed_modes = ["A", "R"]    # Mode L에선 비활성 (egress 필요)

# 이 플러그인이 사용할 DB 테이블 namespace
db_namespace = "scope_guard"  # 테이블은 plugin_scope_guard__* prefix
```

#### 6.3.2 Hook 라이프사이클 (8지점)

| Hook | 호출 시점 | 가능한 반환값 |
|---|---|---|
| `on_init` | 프록시 부팅 시 1회 | (none) |
| `on_request_received` | 요청 수신 직후, 검증 전 | PASS / BLOCK / TRANSFORM |
| `before_forward` | 검증 후, 업스트림 호출 직전 | PASS / BLOCK / TRANSFORM |
| `on_upstream_response_start` | 업스트림 응답 헤더 도착 시 | PASS / ABORT |
| `on_response_chunk` | 응답 chunk마다 | PASS / ABORT |
| `on_response_complete` | message_stop 도착 시 | (none, 관측만) |
| `on_persisted` | 로컬 DB에 저장 끝난 후 (비동기 OK) | (none) |
| `on_shutdown` | 종료 시 | (none) |

`BLOCK`/`ABORT` 결정은 합성 SSE 응답으로 사용자에게 전달되고, 그 시점에 후속 hook은
스킵된다.

#### 6.3.3 Capability 어휘 (잠정 목록)

| Capability | 의미 |
|---|---|
| `read_request_metadata` | 모델명, 토큰 수, 헤더(스크럽됨), 타이밍 |
| `read_request_content` | 사용자 prompt·tool_result의 본문 |
| `read_response_metadata` | 응답 메타(usage 등) |
| `read_response_content` | 응답 본문 (스트림 포함) |
| `modify_request` | 업스트림 호출 전에 요청 변형 |
| `block_request` | 합성 차단 응답 |
| `abort_response` | 응답 스트림 중단 |
| `read_persisted_data` | 로컬 DB 읽기 |
| `write_plugin_tables` | 자기 namespace 테이블에 쓰기 |
| `egress_http` | EgressGuard 통한 외부 HTTP (allowlist 필수) |

운영자가 plugin install 시점에 manifest를 보고 capability를 승인. 이후 변경되면
재승인 필요(서명 키로 manifest 변조 검출).

#### 6.3.4 격리

플러그인은 코어와 같은 Python 프로세스에서 돌지만(in-process) 다음 보호:
- Plugin 함수 호출은 timeout + 예외 격리. 한 plugin이 죽어도 코어는 계속.
- 코어는 plugin에 *함수 인자로* 데이터를 전달. 글로벌 상태 공유 없음.
- 외부 통신은 EgressGuard 단일 경로. 플러그인 코드가 raw socket/requests 라이브러리
  사용하더라도 정책상 금지(스타일가이드 + 코드 리뷰; 강제 격리는 Phase 3 subprocess).
- DB 접근은 `db_namespace`가 prefix된 테이블로 한정된 핸들 제공.

### 6.4 어댑터 추상화

여러 LLM provider 지원을 위해 인터페이스만 추상.

```python
class ProviderAdapter(Protocol):
    name: str                              # "anthropic", "openai", ...
    def match(self, request) -> bool: ...
    def parse_request(self, raw) -> RequestRecord: ...
    def parse_response_stream(self, stream) -> AsyncIterator[Event]: ...
    def upstream_url(self, request) -> str: ...
```

지금은 `llm_tracker.adapters.anthropic`만 구현. OpenAI/Gemini는 후순위.

## 7. 보안 모델

### 7.1 콘텐츠 레벨

데이터는 4단계 레벨로 표현. Plugin이 hook에서 받는 데이터는 *모드별 default 레벨로
강등된 형태*.

| 레벨 | 의미 |
|---|---|
| L0 | 메타데이터만 — 토큰 수, 모델명, 지연, 툴 이름, status code |
| L1 | L0 + 본문의 결정적 해시(SHA-256). 길이 정보 |
| L2 | L0 + 스크러빙된 본문 (시크릿/PII/경로/이메일/IP 제거됨) |
| L3 | 원본 (스크러빙 적용 후의 raw) |

Mode L의 default는 L0–L1, Mode A는 L0, Mode R은 사용자 opt-in 후 L2–L3까지.
플러그인은 자기 manifest에 *최소 필요 레벨*을 선언; 운영자가 그 레벨을 plugin에
승인할 때만 해당 hook이 그 레벨로 데이터를 받는다.

### 7.2 Capability 시스템

§6.3.3의 capability 목록이 그대로 *권한 모델*. 핵심 불변식:

- 플러그인은 manifest에 선언된 capability 외엔 행동하지 못한다.
- 운영자 승인 없이 capability는 활성화되지 않는다.
- Manifest 변조 시 서명 검증으로 검출되어 plugin은 비활성화.
- 모든 capability 호출은 audit log에 (plugin, hook, capability, 결과)로 기록.

### 7.3 Egress 통제

본 프레임워크의 가장 강하게 강제할 보안 경계.

- **모든** 외부 HTTP는 EgressGuard 통과. 플러그인 코드 어디에서도 raw HTTP 라이브러리
  사용 금지(코드 리뷰 + lint rule).
- EgressGuard는 plugin manifest의 `egress_destinations` allowlist를 strict 매치.
  와일드카드 허용 안 함(예: `https://api.anthropic.com`은 OK, `https://*.com`은 거부).
- Mode L에선 EgressGuard 자체가 LLM 업스트림 외 모든 destination을 거부 — 플러그인이
  manifest에 적었어도.
- Mode A에선 운영자가 명시 승인한 destination만 허용.
- 모든 egress 시도(성공/거부)는 audit log.

업스트림 LLM(api.anthropic.com)은 코어가 직접 호출하므로 EgressGuard와 별개 경로지만,
같은 audit log에 기록.

### 7.4 Audit log

```sql
CREATE TABLE audit_log (
  id          TEXT PRIMARY KEY,             -- ULID
  ts          INTEGER NOT NULL,             -- epoch ms
  kind        TEXT NOT NULL,                -- plugin_loaded | hook_invoked |
                                            -- capability_used | egress_attempt |
                                            -- egress_blocked | manifest_rejected
  plugin      TEXT,                         -- 해당 plugin name (있으면)
  hook        TEXT,                         -- 해당 hook (있으면)
  capability  TEXT,                         -- 해당 capability (있으면)
  destination TEXT,                         -- egress destination (있으면)
  outcome     TEXT NOT NULL,                -- ok | denied | error
  detail_json TEXT
);
CREATE INDEX idx_audit_ts ON audit_log(ts);
CREATE INDEX idx_audit_plugin ON audit_log(plugin);
```

운영자는 `llm-tracker audit ...` CLI로 검토. Append-only(트리거로 update/delete 막음).

## 8. 배포 모드

운영자가 시작 시 모드 선택. 모드는 capability 허용 범위와 콘텐츠 레벨 기본값을 강제.

| | Mode L (Local-only) | Mode A (Audit-light) | Mode R (Research) |
|---|---|---|---|
| 사용 시나리오 | 극비 데이터 다루는 고객 | 컴플라이언스/경량 추적 | 연구 데이터 수집 |
| egress capability | 거부 | 운영자 승인된 1개만 | manifest 기반 다수 |
| 기본 콘텐츠 레벨 (외부 흐름) | n/a (외부 없음) | L0 | L1–L3 (opt-in 따라) |
| 사용자 동의 흐름 | 불요 | "메타데이터 송신" 1회 | task별 opt-in |
| 가능한 plugin 예 | scope_guard(local judge) | scope_guard, audit_export | + drift_metrics, upload_sink |

모드 전환은 재시작 + 운영자 재승인 필요 (silent escalation 방지).

## 9. 데이터 모델

### 9.1 코어 테이블 (모든 모드 공통)

```sql
CREATE TABLE exchanges (
  id              TEXT PRIMARY KEY,
  session_id      TEXT NOT NULL,
  started_at      INTEGER NOT NULL,
  ended_at        INTEGER,
  provider        TEXT NOT NULL,
  endpoint        TEXT NOT NULL,
  model_requested TEXT,
  model_served    TEXT,
  status_code     INTEGER,
  input_tokens    INTEGER,
  output_tokens   INTEGER,
  cache_read_tokens  INTEGER,
  cache_write_tokens INTEGER,
  latency_ms      INTEGER,
  stop_reason     TEXT,
  tool_call_count INTEGER DEFAULT 0,
  content_level   TEXT NOT NULL,   -- L0 | L1 | L2 | L3
  blocked_by      TEXT              -- 차단된 경우 plugin name
);

CREATE TABLE events (
  id           TEXT PRIMARY KEY,
  exchange_id  TEXT NOT NULL REFERENCES exchanges(id),
  seq          INTEGER NOT NULL,
  ts           INTEGER NOT NULL,
  kind         TEXT NOT NULL,
  payload_json TEXT
);

CREATE TABLE tool_calls (
  id           TEXT PRIMARY KEY,
  exchange_id  TEXT NOT NULL REFERENCES exchanges(id),
  name         TEXT NOT NULL,
  input_hash   TEXT,
  input_json   TEXT,
  result_hash  TEXT,
  result_json  TEXT
);

-- audit_log는 §7.4

CREATE INDEX idx_exchanges_started ON exchanges(started_at);
CREATE INDEX idx_events_exchange   ON events(exchange_id, seq);
```

### 9.2 플러그인 테이블 (각 plugin이 자기 namespace에서 관리)

플러그인은 자기 manifest의 `db_namespace` 안에서만 테이블을 생성. 명명 규칙:
`plugin_<namespace>__<table_name>`. 마이그레이션은 plugin이 자기 Alembic version
디렉토리로 관리, 코어가 plugin install 시 적용.

예: scope_guard 플러그인은 `plugin_scope_guard__task_definitions`,
`plugin_scope_guard__verdicts` 테이블을 자기 alembic으로 만든다 (구체 스키마는
ADR-0002 / `docs/plugins/scope_guard.md`).

## 10. 기술 리스크

| 리스크 | 검증 방법 | 통과 조건 |
|---|---|---|
| 플러그인 hook이 first-token-latency 누적 | 빈 plugin·평균 plugin 부하별 latency 측정 | hook당 +5ms 이내 |
| Plugin이 죽었을 때 코어 영향 | 일부러 throw하는 plugin 부하 시험 | 코어 무영향 |
| EgressGuard 우회 시도 | plugin이 raw httpx 호출하는 시나리오 | 정적 lint로 차단 + 런타임 검출 (best-effort) |
| 모드 escalation (L→A→R 무단 변경) | 설정 파일 변조 시뮬레이션 | 시작 거부 |
| Manifest 변조로 capability 추가 | 가짜 manifest 주입 | 서명 검증으로 거부 |
| 스크러빙 누락 | 시크릿 포함 가짜 세션 → SQLite + plugin payload grep | 패턴 0건 |
| 코어 SSE tee가 사용자 지연 유발 | 직접 호출 vs 프록시 경유 first-token-latency | +50ms 이내 |

## 11. 의존성 (계획)

- `fastapi`, `uvicorn[standard]`, `httpx[http2]`
- `pydantic`, `pydantic-settings`
- `structlog`
- `typer`
- `sqlalchemy[asyncio]`, `aiosqlite`, `alembic`
- `python-ulid`, `keyring`
- 서명: `pynacl` (ed25519)
- dev: `pytest`, `pytest-asyncio`, `respx`, `ruff`, `mypy`

플러그인이 추가 의존성을 들고 오는 건 자유. 코어 의존성은 의도적으로 좁게 유지.

## 12. 오픈 이슈

- 세션 식별 전략 (Claude Code의 대화 단위 묶기). 휴리스틱 vs 메타데이터 활용.
- Anthropic API ToS와의 호환성 (법무 자문).
- 스크러빙을 코어가 강제(plugin은 후처리 기회만)할지, plugin이 자기 만족까지 추가
  스크러브할지 — 기본은 *코어가 강제하고 plugin은 추가만 가능*.
- Plugin 격리를 in-process(현재) → subprocess/seccomp(Phase 3)로 갈지 시점.
- 플러그인 서명·신뢰 모델 (운영자 자체 키 vs 우리 서명 키).
- ADR-0003(distribution): 프레임워크 코어 + plugin 분리 배포 모델 확정 필요.

## 13. 부록

### 13.1 부록 A — Reference upload sink 플러그인 (Mode R 용)

ADR-0007에 따라 우리가 reference로 제공하는 plugin. **코어와 별도 패키지**.

- 패키지명(잠정): `llm_tracker_plugin_supabase_sink`
- 동작: `on_persisted` hook에서 exchange 레코드를 배치로 Supabase Postgres에 업로드.
- 필요 capability: `read_persisted_data`, `egress_http`
- Egress destination: 운영자가 자기 Supabase URL을 manifest 검토 시 입력
- 호스팅 권장(연구 운영자용): Fly.io 무료 한도에 같은 코드베이스의 `llm_tracker_server`
  앱 배포. Supabase는 일반 Postgres 프로토콜로만 사용(RPC/RLS/Edge Function 사용 금지).

자세한 기능과 운영 매뉴얼은 `docs/plugins/upload_sink.md`(Phase 2 작성 예정).

### 13.2 부록 B — Migration-friendly 코드 구조

코어와 reference plugin 모두 동일 원칙. 자세한 트리는 `docs/plugins.md`.

- 레이어: `api/` → `domain/` → `storage/`. `domain/`은 IO 모름.
- DB 접근은 `storage/repositories/`만. 표준 SQL 위주, vendor lock-in 회피.
- 마이그레이션은 Alembic. Plugin도 자기 alembic 디렉토리.
- `DATABASE_URL` 환경변수 한 줄로 DB 교체 가능.

---

## 참고

- 단계별 마일스톤: `docs/roadmap.md`
- 결정 기록: `docs/decisions/`
- 플러그인 작성 가이드: `docs/plugins.md`
- 배포 분석: `docs/distribution.md`
- Claude Code 작업 규칙: `/CLAUDE.md`
