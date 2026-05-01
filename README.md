# Userfriendly

Claude Code (및 유사 CLI 기반 코딩 에이전트)의 LLM API 트래픽을 관측·분석하고,
필요시 개입(intervention)할 수 있게 해주는 **로컬 사이드카 프록시**.

상위 프로젝트의 일부로서 이 리포지토리가 담당하는 범위는 "트래픽 관측·수집·
(선택적) 개입 레이어"이며, 지표 설계와 질문 세트 큐레이션은 다른 구성원이 담당한다.

## 한 줄 요약

사용자는 평소처럼 Claude Code를 쓰고, 우리는 그 사이에 투명 프록시를 끼워
모든 요청/응답을 구조화해서 기록한다. 중앙 서버로는 **스크러빙된 데이터만** 업로드된다.

## 빠른 시작

아직 구현 전. Phase 0 완료 후 이 섹션을 채운다.

사용자 관점의 실행 흐름은 다음 형태가 될 예정:

```bash
# 로컬 프록시 기동
llm-tracker start

# Claude Code가 우리 프록시를 보도록 설정
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787

# 평소처럼 사용
claude
```

## 문서

- `docs/design.md` — 전체 설계 (아키텍처, 컴포넌트, 데이터 모델, 리스크)
- `docs/roadmap.md` — 단계별 마일스톤
- `docs/decisions/` — ADR (아키텍처 결정 기록)
- `docs/worklog/` — Claude Code 작업 로그

## Claude Code로 작업할 때

반드시 `CLAUDE.md`를 먼저 읽어주세요. 작업 추적·문서화 규칙이 정의돼 있습니다.
