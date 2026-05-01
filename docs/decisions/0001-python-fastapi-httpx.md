# ADR-0001 · 언어 및 프록시 프레임워크: Python + FastAPI + httpx

- **상태**: Accepted
- **날짜**: 2026-04-25
- **작성자**: Claude Cowork (사용자 승인)
- **관련**: `docs/design.md §2, §5, §9`

## 맥락

상위 프로젝트에서 이 리포지토리의 역할은 Claude Code의 API 트래픽을 가로채
관측하고 선택적으로 개입하는 로컬 사이드카를 만드는 것이다. 사용자(팀)는 Python을
선호한다. 프록시는 **HTTP SSE 스트리밍을 저지연으로 중계하면서 동시에 tee** 해야 하고,
asyncio 기반 비동기 처리가 자연스러워야 한다.

## 고려한 선택지

1. **Python + FastAPI + httpx**
   - 장점: 팀 친숙도. httpx의 `AsyncClient.stream()`이 SSE 스트림 tee에 적합.
     FastAPI의 `StreamingResponse`로 사용자 방향 전달도 간단. `respx`로 테스트 용이.
   - 단점: Node/Go 대비 초당 요청 throughput 낮음. 단, 로컬 사이드카는 단일 사용자
     단일 에이전트 트래픽이라 문제 안 됨.

2. **Python + aiohttp (서버/클라이언트 통합)**
   - 장점: 의존성 하나로 서버·클라이언트 모두 해결.
   - 단점: FastAPI 대비 팀·LLM 생태계 익숙도 낮음. 타입/문서화는 약점.

3. **Node/TypeScript + undici**
   - 장점: 스트리밍·SSE 처리가 런타임 수준에서 매끄러움. Anthropic SDK의 레퍼런스
     구현도 TS.
   - 단점: 팀 선호와 어긋남. 지표 담당자와의 데이터 분석 통합 비용.

4. **Go + net/http**
   - 장점: 단일 바이너리 배포, 저지연.
   - 단점: 팀 선호 어긋남. Python 스크럽/분석 코드와 이중 스택이 됨.

## 결정

**옵션 1: Python 3.11+, FastAPI, httpx**.

- 팀 Python 선호와 직결.
- httpx는 stream 지원과 async 모델이 명확. `respx`로 단위/통합 테스트 모두 편함.
- 연구용 로컬 사이드카 성격상 throughput 요구가 낮아 Python의 비용이 부담되지 않음.
- 지표 담당자 쪽 스택(pandas/sklearn 류)과 언어 통일.

## 결과

- 공식 런타임: Python 3.11+.
- 서버 프레임워크: FastAPI (+ uvicorn).
- 업스트림 HTTP: httpx (HTTP/2 활성화).
- CLI: Typer.
- 로깅: structlog.
- 설정: pydantic-settings.
- 로컬 저장: SQLite (`sqlalchemy` + `aiosqlite` 또는 `sqlite-utils`; Phase 1에서 재결정).

### 포기하는 것

- Node/Go로 얻을 수 있었을 극한 저지연·단일 바이너리 배포 편의.
- Anthropic 공식 TS SDK의 최신 동향을 레퍼런스로 바로 가져다 쓰기 어려움(JSON 포맷은
  같으므로 파싱만 재구현).

### 되돌리기 난이도

중. 프록시 코어는 이식 가능하지만, Phase 1 이후 파이썬 생태계에 걸친 스크럽/업로드
/지표 연계가 쌓이면 교체 비용이 급격히 증가한다. 따라서 **Phase 1 완료 전에** 재검토
기회가 있으면 마지막으로 점검하고, 그 이후엔 고정.

## 미해결

없음.
