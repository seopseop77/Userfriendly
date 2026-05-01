# 로드맵

각 단계의 **완료 조건(Definition of Done)** 을 명시한다. 단계를 건너뛰지 않는다.

## Phase 0 — 뼈대 & 투명 포워더 (MVP of MVP)

목표: Claude Code가 프록시를 경유해 정상적으로 동작한다. 관측은 최소.

- [ ] `pyproject.toml` 실제 의존성 채우고 `pip install -e .[dev]` 성공.
- [ ] FastAPI 기반 `/v1/messages` catch-all 라우트.
- [ ] `httpx`로 업스트림 포워딩. SSE 스트리밍 그대로 전달.
- [ ] `llm-tracker start` CLI (Typer) — 기본 포트 8787.
- [ ] 텍스트 로그 파일 하나에 요청/응답 헤더·타이밍 append (스크러빙 아직 없음).
- [ ] Claude Code로 로컬 end-to-end 세션 통과 확인.
- [ ] PoC 측정: first-token-latency 직접 호출 대비 +50ms 이내.

완료 조건: 연구자가 본 프록시를 켠 채 Claude Code를 평소처럼 쓸 수 있다.

## Phase 1 — 구조화 저장 & 스크러빙 & 업로드

목표: 분석 가능한 구조로 저장되고, 중앙으로 보내진다.

- [ ] SSE Extractor: `message_start`, `content_block_*`, `tool_use`, `message_delta`, `message_stop` 모두 구조화.
- [ ] SQLite 스키마 v1 적용(`exchanges`, `events`, `tool_calls`).
- [ ] Scrubber L0/L1 기본, L2 opt-in 플래그.
- [ ] Uploader 데몬 (배치 + 지수 백오프).
- [ ] 중앙 Ingest API 스펙 확정 (별도 문서 or 별도 레포).
- [ ] 시크릿/PII 누수 검증 테스트 통과.
- [ ] Phase 1 완료 시점의 이벤트 스키마를 ADR로 봉인.

## Phase 2 — Task-scope guard (1차 개입)

목표: 사용자가 등록된 작업과 무관한 요청을 하면 자동으로 차단한다.
설계는 `design.md §5.4`, ADR-0002 참조.

- [ ] `TaskDefinition` 스키마와 로컬 캐시 테이블(`task_definitions`).
- [ ] 중앙에서 task definition 가져오기 (시작 시 + 주기 동기화). 서명 검증 포함.
- [ ] User 메시지 추출기 — `messages` 배열에서 마지막 `role: user`의 text content만 분리.
- [ ] Stage 1 임베딩 judge — positive/negative examples를 사전 임베딩, 코사인 비교.
- [ ] Stage 2 LLM judge — 저렴한 모델로 `{verdict, reason}` JSON 응답 강제.
- [ ] `(task_id, message_hash)` LRU 캐시.
- [ ] `out_of_scope` 시: 업스트림 호출 스킵 + 합성 SSE 응답으로 사용자에게 차단 통지.
- [ ] 차단 통지 메시지에 "왜 차단됐는지(요약) + 정상 사용 예시" 포함.
- [ ] 모든 판정을 `scope_verdicts` 테이블에 기록.
- [ ] 평가셋: 각 task당 in/out 프롬프트 50개씩 수동 라벨링 → 자동 회귀 테스트.
- [ ] False positive ≤ 5%, prompt-injection 우회 ≤ 1건/30 (PoC 통과 조건).

완료 조건: 연구자/직원이 등록된 작업 외 용도로 Claude Code를 쓰려 시도하면
프록시가 안정적으로 차단하고, 정상 작업은 5% 이내의 false positive로 통과한다.

## Phase 3 — 응답 측 정책 & 멀티 프로바이더 & 분석 UI

범위 열릴 경우에만 착수.

- [ ] 응답 SSE 스트림에 대한 정책 엔진 (이상 패턴 감지 시 abort/notify).
- [ ] 룰 핫리로드(중앙에서 룰 갱신 받기).
- [ ] OpenAI/Gemini 어댑터.
- [ ] Grafana 대시보드 또는 간단한 내부 UI.
- [ ] 지표 담당자가 정의한 drift 지표 계산 파이프라인과 연결.
