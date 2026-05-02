# ADR-0007 · 중앙 서버를 *옵션 플러그인*으로 강등 — Supersede ADR-0004

- **상태**: Accepted (supersedes ADR-0004)
- **날짜**: 2026-05-01
- **작성자**: Claude Cowork (사용자 승인)
- **관련**: ADR-0004, ADR-0005, ADR-0006

## 맥락

ADR-0004는 데모용 중앙 서버 스택을 Supabase + Fly.io + 동일 레포로 확정했다.
이때의 가정은 "모든 deployment에서 데이터는 중앙으로 흐른다"였다.

ADR-0005·0006에서 framework-first 모델로 전환하면서 그 가정이 깨졌다. 고객 시나리오
(Mode L)는 외부로 데이터를 보내지 않는다. Mode A는 최소 메타만, Mode R만 풍부한
데이터를 외부로 보낸다. 따라서 "중앙 서버"는 코어 컴포넌트가 아니라 **Mode R 운영을
위한 reference 플러그인**으로 위치가 변해야 한다.

## 결정

**1) 중앙 서버 코드는 reference upload sink 플러그인으로 재배치.**

- 패키지명(잠정): `llm_tracker_plugin_supabase_sink` (또는 같은 의도의 이름).
- 본 리포 동일 트리에 `src/llm_tracker_plugin_supabase_sink/`로 둔다 (별도 레포로
  뺄지는 Phase 2에서 재검토).
- 이 플러그인은 `on_persisted` hook에서 exchange를 Supabase Postgres로 배치 업로드.
- 필요 capability: `read_persisted_data`, `egress_http`.
- 운영자가 manifest에 자기 Supabase URL을 destination으로 입력 후 승인.

**2) 서버 앱 코드(`src/llm_tracker_server/`)는 reference 운영자용 *수신측* 으로 유지.**

- 운영자가 자기 Supabase에 받은 데이터를 정리·분석하기 위한 FastAPI 앱.
- Fly.io 배포는 그대로 reference로 둔다(필수 아님).
- 코어 프레임워크에서 *컴파일 타임 의존* 없음. 양측은 독립 패키지.

**3) ADR-0004의 결정 사항 자체(Supabase 사용, vendor lock-in 회피, Fly.io 호스팅)는
   reference 플러그인의 권장 셋업으로 보존.**

## 결과

- Mode L 사용자에겐 본 plugin이 *처음부터 비활성화*. 설치할 필요 없음.
- Mode R 운영자만 이 plugin을 추가 설치하고 manifest 승인.
- "기본 deployment에 중앙 서버 비용/셋업 부담"이 사라짐. 코어 셋업이 단순.
- 협업자들이 다른 sink(예: 자체 분석 백엔드, 회사 SIEM)를 만들 수 있는 길이 열림.

### 포기하는 것

- "코어가 곧 데이터 수집 시스템"이라는 직관적 일체감.
- 코어와 서버 앱 사이의 즉시적 코드 공유 — 모델/스키마는 별도 공통 패키지(또는
  플러그인 SDK)에 두어 양측이 import.

### 되돌리기 난이도

낮음. 플러그인 인터페이스가 안정적이면 sink 플러그인은 자유로이 갈아낄 수 있다.
ADR-0005를 되돌리지 않는 한 이 결정도 유지.

## 미해결

- 모델/스키마 공유를 위한 공통 패키지(`llm_tracker_common` 또는 `llm_tracker_sdk`)
  분리 시점.
- 사용자 opt-in 동의서 흐름 — Mode R 진입 시 어떤 화면/문서를 거치는지.
