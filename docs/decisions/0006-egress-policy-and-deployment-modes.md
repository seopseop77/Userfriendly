# ADR-0006 · Egress 정책과 배포 모드 (L/A/R)

- **상태**: Accepted
- **날짜**: 2026-05-01
- **작성자**: Claude Cowork (사용자 승인)
- **관련**: `docs/design.md §7, §8`

## 맥락

본 프레임워크는 두 종류의 사용처를 동시에 지원해야 한다.

- **고객 시나리오**: 회사 업무에 Claude Code를 쓰는 사용자. 로그가 외부로 나가는 걸
  꺼린다. 극비 데이터 노출 위험.
- **연구 시나리오**: drift 추적·지표 개발을 위해 풍부한 데이터를 중앙으로 수집하고
  싶은 운영자. 사용자 opt-in 후.

두 시나리오를 같은 코어 위에서 안전하게 지원하려면, 데이터 egress가 *기본 OFF*이고
*명시적 승인*이 있을 때만 일어나야 한다. 그리고 어떤 조건에서 어떤 데이터가 나갈 수
있는지를 코드 곳곳에 흩어 두지 말고, **모드(mode)** 라는 단일 정책 축으로 강제해야
한다.

## 결정

**1) 모든 외부 HTTP는 EgressGuard 단일 경로.**

플러그인이든 코어 보조 컴포넌트든 외부로 나가려면 EgressGuard에 요청한다.
EgressGuard는 다음을 검사:

- 요청자(plugin)에 `egress_http` capability가 부여돼 있는가.
- 대상 URL이 plugin manifest의 `egress_destinations` allowlist에 있는가
  (정확 매치, 와일드카드 금지).
- 현재 deployment mode에서 그 capability가 허용되는가.

세 검사 모두 통과해야 forward. 모든 시도(성공/거부)는 audit_log.

업스트림 LLM(api.anthropic.com 등)은 코어가 직접 호출하므로 EgressGuard 경로가 별개
지만, 같은 audit log에 기록.

**2) 세 deployment mode 정의.**

| 모드 | 사용처 | egress 정책 | 콘텐츠 레벨 기본 |
|---|---|---|---|
| **L** Local-only | 극비 고객 | LLM 업스트림 외 *전부 거부* | n/a |
| **A** Audit-light | 컴플라이언스/경량 추적 | 운영자 승인 1개 destination, L0만 | L0 |
| **R** Research | 연구 데이터 수집 | manifest 기반 다수, 사용자 opt-in 후 L1–L3 | L1 (opt-in 시 L2/L3) |

모드는 운영자가 시작 시 fix. 변경하려면 재시작 + 재승인 (silent escalation 방지).

**3) 콘텐츠 레벨 강등.**

코어가 plugin에 데이터를 전달할 때 *모드별 maximum 레벨 + plugin이 manifest에 선언한
최소 필요 레벨*의 교집합으로 강등. Mode L에선 plugin이 L3 요청해도 L0/L1만 받는다.
Plugin이 받지 못하는 정보는 처음부터 도달하지 않으므로 누수 위험 자체가 사라진다.

## 결과

- 코어가 작은 *정책 평가기*를 갖는다 — `(plugin, capability, destination, mode)` →
  allow/deny.
- 새 모드 추가는 작은 코어 변경(허용 매트릭스 한 줄). 새 capability 추가는 ADR 필요.
- 모든 보안 이벤트는 단일 audit_log로 통합되어 운영자 검토가 쉽다.
- 정적 lint rule과 코드 리뷰로 plugin이 raw HTTP 라이브러리(`requests`, `urllib`,
  `socket`, `httpx.AsyncClient` 등)를 import하지 못하게 강제. EgressGuard가 제공하는
  `egress.fetch(...)` 만 허용.

### 포기하는 것

- 운영자가 "그냥 잠깐 쓰고 싶은데" 식 일회성 capability 부여 편의.
- 운영자 의도와 무관하게 plugin이 새 destination에 알아서 붙는 자유.

### 되돌리기 난이도

낮음. EgressGuard와 mode 정책은 코어 한 모듈로 격리된다. 정책을 느슨히 하는 건
설정 변경으로 가능, 강하게 만드는 건 plugin 사정에 따라 영향.

## 미해결

- in-process Python 환경에서 plugin이 EgressGuard를 우회하는 시도(`socket.socket()`
  직접 사용 등)에 대한 *런타임 강제*. Phase 3 subprocess 격리 전엔 정적 lint +
  코드 리뷰가 best-effort. 운영자가 신뢰하지 않는 plugin은 깔지 말아야 한다는 정책
  유지.
- audit_log 자체의 무결성 (운영자가 audit를 지우지 못하게). append-only 트리거는
  데이터베이스 차원에서, 그래도 운영자가 DB 파일을 직접 건드릴 수 있으므로 한계 인정.
- 사용자 opt-in 흐름의 UX (CLI 프롬프트 vs 별도 툴).
