# 플러그인 작성 가이드

본 프레임워크의 *기능*은 모두 플러그인으로 만들어진다. 본 문서는 플러그인 작성자가
참고할 계약(contract)을 정의한다. 코어 설계는 `design.md`, 보안 정책은 ADR-0006.

> **상태**: 골격(스켈레톤). Phase 0 코어 작업 완료 후 Phase 1a에서 SDK와 함께 본
> 문서를 채운다. 지금은 플러그인을 작성하려는 협업자가 *무엇을 약속받고 무엇을
> 요청할 수 있는지* 보고 토론할 수 있을 정도까지.

## 1. 플러그인이란

- Python 패키지로 배포된다.
- setuptools entry point(`llm_tracker.plugins`)로 자기를 등록한다.
- 루트에 `plugin.toml` manifest를 가진다.
- 한 개 이상의 hook에 binding 한다.
- manifest에 선언된 capability 외엔 *아무것도 못 한다* (강제됨).

## 2. plugin.toml 스키마

```toml
name = "<plugin-name>"                # 영숫자 + 하이픈/언더스코어. 코어 namespace가 됨.
version = "0.1.0"
description = "..."
author = "..."

# 코어가 어느 버전까지 호환하는가
core_version_constraint = ">=0.1.0,<0.2.0"

# 등록할 hook 이름
hooks = ["before_forward", "on_persisted"]

# 요구 capability (운영자 승인 대상)
capabilities = ["read_request_content", "block_request"]

# 외부 통신 시 destination allowlist (정확 매치, 와일드카드 금지)
egress_destinations = []  # 비어 있으면 외부 통신 안 함

# 동작 가능한 deployment mode
allowed_modes = ["A", "R"]

# 자기 namespace에서 만들 DB 테이블 prefix
db_namespace = "<plugin-name>"

# 코어가 plugin에 전달할 *최소 필요* 콘텐츠 레벨
required_content_level = "L2"

# (선택) 운영자가 입력해야 할 설정 schema
[config_schema]
my_field = "string"
```

## 3. Hook 라이프사이클

| Hook | 호출 시점 | 반환 의미 |
|---|---|---|
| `on_init` | 프록시 부팅 시 1회 | (none) |
| `on_request_received` | 요청 수신 직후 | `Pass` / `Block(reason)` / `Transform(req)` |
| `before_forward` | 업스트림 호출 직전 | `Pass` / `Block(reason)` / `Transform(req)` |
| `on_upstream_response_start` | 응답 헤더 도착 | `Pass` / `Abort(reason)` |
| `on_response_chunk` | 응답 chunk 마다 | `Pass` / `Abort(reason)` |
| `on_response_complete` | message_stop | (관측만) |
| `on_persisted` | 로컬 DB 저장 완료 후 (async OK) | (관측만) |
| `on_shutdown` | 종료 시 | (none) |

`Block`/`Abort`은 합성 SSE 응답으로 사용자에게 차단 사유를 전달한다.

## 4. Capability 어휘

| Capability | 의미 |
|---|---|
| `read_request_metadata` | 모델, 토큰 수, 헤더(스크럽됨) |
| `read_request_content` | 사용자 prompt·tool_result 본문 |
| `read_response_metadata` | 응답 usage, stop_reason |
| `read_response_content` | 응답 본문 (스트림 chunk 포함) |
| `modify_request` | 업스트림 호출 전 요청 수정 |
| `block_request` | 합성 차단 응답 |
| `abort_response` | 응답 스트림 중단 |
| `read_persisted_data` | 로컬 SQLite 읽기 |
| `write_plugin_tables` | 자기 namespace 테이블 쓰기 |
| `egress_http` | EgressGuard 통한 외부 HTTP |

## 5. 플러그인 코드 골격 (예정 SDK)

```python
# src/my_plugin/__init__.py
from llm_tracker_sdk import BasePlugin, hook, Pass, Block

class MyPlugin(BasePlugin):

    @hook("before_forward")
    async def check_scope(self, ctx):
        user_msg = ctx.last_user_message_text   # capability에 따라 마스킹된 형태
        if "..." in user_msg:
            return Block(reason="...")
        return Pass()

    @hook("on_persisted")
    async def maybe_export(self, ctx, exchange_id):
        # ctx.egress.fetch(...) 만 사용 가능. raw httpx 금지.
        ...
```

## 6. DB 테이블

플러그인은 자기 `db_namespace` 안에서만 테이블을 만든다. 명명: `plugin_<namespace>__<table>`.
스키마 변경은 자기 디렉토리의 Alembic version으로 관리. 코어가 install 시 자동 적용.

## 7. 외부 통신

`requests`/`urllib`/`httpx` 직접 사용 **금지** — 정적 lint와 코드 리뷰로 차단.
모든 외부 통신은 SDK가 제공하는 `ctx.egress.fetch(url, ...)` 한 함수만 사용.
EgressGuard가 manifest의 `egress_destinations`와 정확 매치 + 운영자 승인 + 모드
허용을 검사한다.

## 8. 모드별 행동

플러그인 manifest의 `allowed_modes`에 따라 활성/비활성. 예:
- `["L", "A", "R"]` 어디서든.
- `["A", "R"]` 외부 통신 필요한 plugin (Mode L에선 비활성).
- `["R"]` 데이터 업로드 sink.

## 9. 격리와 신뢰

Phase 1까진 in-process. plugin이 마음먹고 우회하면 raw socket 사용 가능 — 정책으론
금지지만 강제 isolation은 Phase 3 subprocess에서. 따라서 *운영자가 신뢰하지 않는
plugin은 깔지 말아야 한다*. Manifest 서명 검증, 코드 리뷰, 명시적 capability 승인이
1차 방어선.

## 10. Reference 플러그인

- `scope_guard` — 작업 범위 강제 (ADR-0002 스펙).
- `supabase_sink` — Mode R 데이터 중앙 업로드 (ADR-0007).
- `hello_world` — Phase 0 검증용 no-op.

각 reference plugin은 별도 패키지로 빌드되며, 본 리포 트리에 함께 둔다(추후 분리
가능). 디렉토리 위치는 `src/llm_tracker_plugin_<name>/`.
