# 로드맵 (framework-first)

이 로드맵은 **프레임워크 → 플러그인 SDK → 첫 플러그인 → 확장**의 순서로 짜였다.
구체 기능(scope guard, drift 추적 등)을 코어에 넣지 않는다 — 모두 플러그인.

각 단계의 **완료 조건(Definition of Done)** 을 명시한다.

## Phase 0 — 코어 프레임워크 뼈대

목표: 빈 프록시(투명 포워더)에 plugin host 골격이 붙어서, "아무 일도 하지 않는
빈 plugin"을 로드해서 hook이 호출되는 것까지 확인.

- [ ] `pyproject.toml` 의존성 채우고 `pip install -e .[dev]` 동작.
- [ ] FastAPI catch-all 라우트 + httpx SSE 투명 포워딩 (Tee 포함).
- [ ] 로컬 SQLite 스키마(`exchanges`, `events`, `tool_calls`, `audit_log`) + Alembic.
- [ ] `llm-tracker` Typer CLI: `init`, `start`, `audit` 골격.
- [ ] PluginHost 골격: setuptools entry-point 로드, manifest 파싱, hook 디스패처.
- [ ] 8개 hook 지점 코어에 박기 (Phase 0엔 dispatch만, 실제 plugin 로직 없음).
- [ ] AuditLog: hook 호출/lifecycle 이벤트 기록.
- [ ] EgressGuard 골격: 외부 HTTP 단일 진입점. Phase 0엔 default deny + LLM
  업스트림만 허용.
- [ ] Mode 설정(L/A/R) — 시작 시 모드 fix.
- [ ] no-op 샘플 플러그인(`hello_world`)이 로드되어 hook 호출이 audit log에 남는지 검증.
- [ ] Claude Code로 end-to-end 정상 동작 확인 (no-op plugin 상태에서).
- [ ] PoC 측정: 직접 호출 대비 first-token-latency +50 ms 이내.

완료 조건: 사용자가 프록시를 켠 채 Claude Code를 평소처럼 쓸 수 있고, 운영자는
audit log에서 hook 호출 흐름을 볼 수 있다.

## Phase 1 — 플러그인 SDK + 첫 플러그인 (`scope_guard`) + 보안 강화

목표: 외부 협업자가 플러그인을 작성할 수 있는 SDK 완비. 첫 플러그인으로
ADR-0002의 task-scope guard를 reference 구현.

### 1a. Plugin SDK
- [ ] `llm_tracker_sdk` 패키지: `BasePlugin`, hook 데코레이터, capability 토큰.
- [ ] `plugin.toml` schema 검증기 + 서명 도구.
- [ ] Plugin 테스트 하니스(가짜 hook 컨텍스트, 가짜 SQLite).
- [ ] `docs/plugins.md` 1차 완성 — 작성 가이드 + 예시.

### 1b. 보안 경계 강화
- [ ] EgressGuard에 plugin 수준 allowlist 강제 + audit.
- [ ] Manifest 서명 검증 (plugin install 시 + 시작 시).
- [ ] Capability 사용 시 audit 로그 강제.
- [ ] 콘텐츠 레벨(L0–L3) 라우팅: 코어가 plugin에 전달하기 전 강등.
- [ ] 모드별 capability 정책 강제 테스트.

### 1c. `scope_guard` 플러그인 (별도 패키지)
- [ ] TaskDefinition 스키마 + 로컬 캐시(`plugin_scope_guard__*`).
- [ ] Stage 1 임베딩 judge (로컬 sentence-transformers).
- [ ] Stage 2 LLM judge — manifest의 egress destination에 등록된 외부 모델.
- [ ] `(task_id, message_hash)` LRU 캐시.
- [ ] `out_of_scope` 시 합성 SSE 응답.
- [ ] 평가셋 50/50, false positive ≤ 5%.

완료 조건: 외부 협업자가 `docs/plugins.md`만 보고 토이 플러그인 하나를 만들 수
있고, `scope_guard`가 정상 차단·통과한다.

## Phase 2 — Reference upload sink + 플러그인 생태계 시작

목표: Mode R 운영자가 데이터를 중앙으로 보낼 수 있는 reference 플러그인 + 협업자
들의 첫 플러그인 받기 시작.

- [ ] `llm_tracker_plugin_supabase_sink`: `on_persisted`에서 배치 업로드, 지수 백오프.
- [ ] `src/llm_tracker_server/`: Supabase 연결, ingest API. Fly.io 배포 fly.toml.
- [ ] 사용자 동의 흐름 (Mode R에서 task별 opt-in).
- [ ] Plugin 호환성/버전 매트릭스 문서화.
- [ ] 협업자가 만든 첫 플러그인 (`drift_metrics` 등) 통합 테스트.

## Phase 3 — 격리 강화 + 멀티 프로바이더 + 분석

후순위. 외부 사용 늘어날 때 착수.

- [ ] Plugin subprocess 격리 옵션 (보안 민감 운영자용).
- [ ] OpenAI/Gemini 어댑터.
- [ ] 분석 인터페이스(SQL 직접 vs REST) 결정 후 구현.
- [ ] 응답 측 정책 plugin 카테고리 (이상 행동 감지).
