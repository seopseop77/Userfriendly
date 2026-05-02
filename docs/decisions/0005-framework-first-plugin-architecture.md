# ADR-0005 · Framework-first 아키텍처 + 플러그인 모델

- **상태**: Accepted
- **날짜**: 2026-05-01
- **작성자**: Claude Cowork (사용자 승인)
- **관련**: `docs/design.md §4–§6`, `docs/roadmap.md`, `docs/plugins.md`

## 맥락

원래 본 리포는 단일 목적 제품(Claude drift 추적 + scope enforcement + 중앙 데이터
수집)을 만들기로 시작했다. 협업자와 논의 후 다음을 인지했다.

1. **추가 기능이 계속 들어올 예정.** 어떤 기능인지 아직 상세 미정. 코어를 자주
   건드리지 않고 새 기능을 얹을 수 있어야 한다.
2. **데이터 흐름 정책이 사용처마다 다르다.** 고객 시나리오는 외부 egress 거부, 연구
   시나리오는 풍부한 수집. 같은 코어가 둘 다 안전하게 지원해야 한다.

위 두 요구가 만나는 답은 *프레임워크 + 플러그인* 모델이다. 코어는 일관된 hook
인터페이스와 보안 경계만 제공하고, 모든 *행동*은 플러그인이 가진다.

## 고려한 선택지

1. **모놀리식**: 모든 기능을 코어에 직접. 단순하지만 새 기능마다 코어 수정 필요,
   고객/연구 데이터 정책 분기를 코드 안에 흩어 두게 됨.
2. **프레임워크 + in-process 플러그인 (Python entry-points)**: 코어가 플러그인을
   로드해 hook으로 dispatch. 플러그인은 같은 프로세스에서 동작. 가벼움.
3. **프레임워크 + subprocess/WASM 플러그인**: 강한 격리. 구현·SDK 부담 큼.

## 결정

**옵션 2 — Python entry-point 기반 in-process 플러그인 모델.** 단, in-process라는
한계를 보안 정책으로 보완한다.

- Plugin은 setuptools entry point(`llm_tracker.plugins`)로 등록.
- 각 plugin은 `plugin.toml` manifest에 hooks/capabilities/egress destinations/
  allowed modes/db namespace를 선언.
- 코어는 manifest 검증·서명 확인 후 hook을 dispatch.
- 8개 hook 지점, 약 10개 capability 어휘 (자세한 건 design.md §6.3).
- 외부 통신은 EgressGuard 단일 경로. Plugin manifest의 destination allowlist
  외엔 거부.
- 모든 hook 호출/capability 사용/egress 시도는 audit_log에 기록.

Phase 3에서 subprocess 격리 옵션을 도입할 수 있도록 hook 인터페이스는 *직렬화 가능한
입출력*만 사용한다 (현재는 in-process Python 객체를 그대로 전달해도 OK이지만, 나중에
직렬화 boundary로 바뀌어도 깨지지 않게 설계).

## 결과

- 코어는 *기능 없는 호스트*. "이 기능을 코어에 넣자"는 거의 항상 잘못된 답.
- scope_guard, drift_metrics, 중앙 업로드 sink 등은 모두 별도 패키지로 분리.
- 협업자는 코어 수정 없이 플러그인 패키지로 기능을 추가할 수 있다.
- 플러그인 SDK가 별도 산출물로 생긴다(`llm_tracker_sdk`, Phase 1 작업).

### 포기하는 것

- 단일 패키지로 모든 기능을 묶는 단순함.
- in-process 격리 한계 — Python 특성상 plugin이 마음먹고 우회하면 raw socket을
  쓸 수 있음. 코드 리뷰·정적 검사·운영자 승인으로 보완하되, 강한 격리는 Phase 3.

### 되돌리기 난이도

높음. Phase 0–1에서 hook 인터페이스를 잘 정의하면, 그 인터페이스를 깨지 않고 코어
기능을 점진 추가하는 건 쉬움. 그러나 한 번 출시된 hook/capability 어휘를 바꾸는 건
모든 플러그인에 영향. 따라서 §8 공개 인터페이스 변경은 ADR 필수.

## 미해결

- 플러그인 서명 모델 — 운영자 자체 키 vs 우리(프로젝트) 서명 키 vs 마켓플레이스. 데모
  단계는 운영자 자체 키로 시작.
- 플러그인 패키지 배포 채널 (PyPI vs 자체 미러 vs Git 직접). ADR-0003 갱신 필요.
- in-process 한계 → subprocess 전환 시점.
