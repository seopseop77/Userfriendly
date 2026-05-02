# ADR-0004 · 중앙 서버 스택: Supabase + Fly.io + 동일 레포

- **상태**: **Superseded by ADR-0007** (중앙 서버는 옵션 플러그인으로 재배치).
  본 ADR의 기술적 결정(Supabase + Fly.io + vendor lock-in 회피)은 reference upload
  sink 플러그인의 권장 셋업으로 보존.
- **날짜**: 2026-05-01
- **작성자**: Claude Cowork (사용자 승인)
- **관련**: `docs/design.md §13.1`, `docs/distribution.md`, ADR-0007

## 맥락

데모 단계의 중앙 서버 스택을 정해야 한다. 옵션 분석은 `design.md §11.2`에 있었고,
사용자는 클라우드 무료 한도(옵션 B)와 Supabase를 명시적으로 선택했다. 앱 호스팅과
코드 위치는 위임받았다.

## 결정

**(1) DB: Supabase Postgres 무료 한도**

- 일반 Postgres 프로토콜로만 접근 (`postgresql://` URI).
- **사용 금지**: Supabase RLS 자동 적용, RPC, Edge Function, Storage, Realtime,
  Auth-as-a-Service 등 Supabase 전용 기능. 이유는 vendor lock-in 회피
  (`design.md §11.8` 원칙 2).
- 대신 사용: 표준 SQL, JSONB(거의 모든 매니지드 Postgres에서 지원), Alembic
  마이그레이션.

**(2) 앱 호스팅: Fly.io 무료 한도**

- Dockerfile 기반 배포. `fly.toml` 한 파일로 설정.
- Persistent VM이므로 콜드스타트로 인한 데모 UX 저해 없음.
- 비교: Render는 sleep 후 콜드스타트 30초+, 데모용으론 비추.
- 비교: Cloud Run은 무료 한도 풍부하지만 구글 콘솔 셋업 부담.

**(3) 코드 위치: 동일 레포 `src/llm_tracker_server/`**

- 로컬 프록시(`src/llm_tracker/`)와 모델·이벤트 스키마·TaskDefinition 정의를
  공유하기 위함. 별도 레포로 가면 양측 drift 위험.
- 패키지 분리는 import 룰로 강제: 서버 코드는 클라이언트 코드 import 금지, 공통
  타입은 `src/llm_tracker_common/`(필요해지면) 같은 별도 패키지로.

## 결과

- 데모 운영자가 만들어야 할 것: Supabase 프로젝트 1개 + Fly.io 앱 1개. 비용 0.
- 모든 DB 접근은 SQLAlchemy 2.0 + Alembic. 표준 Postgres 사용.
- 서명 키는 운영자 머신 생성 → Fly.io secret(`fly secrets set`) 주입. 공개키만 클라
  이언트 코드에 임베딩(서명 검증용).
- 자동 백업: Supabase 무료 한도엔 일일 자동 백업 포함. 추가 백업은 Phase 1 후반.

### 포기하는 것

- Supabase Auth/RPC/Realtime 등 BaaS 편의. 우리 코드로 직접 구현하는 비용.
- Fly.io 외 호스팅으로 옮기려면 `fly.toml` 대체 필요(Dockerfile은 그대로).

### 되돌리기 난이도

낮음.
- DB 이전: `pg_dump` → 새 Postgres → `DATABASE_URL` 변경. Alembic 버전 동일.
- 호스팅 이전: 어떤 PaaS든 Dockerfile 받는 곳이면 거의 그대로.

## 미해결

- 사용자/조직 인증을 자체 토큰으로 갈지, Supabase Auth(편함, vendor 결합 살짝)에
  올라탈지. 데모는 자체 토큰으로 시작 권장(ADR 갱신 후 변경 가능).
- 무료 한도(Supabase 0.5 GB DB, Fly.io 256MB RAM × 3) 모니터링/알림 셋업 시점.
