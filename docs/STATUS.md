# 현재 상태 (resume 진입점)

> **이 파일은 진행 중인 Claude Code 세션이 매 체크포인트에 갱신한다.**
> 새 세션은 가장 먼저 이 파일 → 활성 worklog → `git log -5` 순으로 읽고
> "다음 한 걸음"을 그대로 수행한다. 자세한 규칙은 `/CLAUDE.md §3, §4`.

---

**최종 업데이트**: 2026-05-01 (Cowork; framework pivot 완료, Phase 0 시작 전)
**갱신자**: Claude Cowork

## 현 단계

- **Phase**: Phase 0 — 코어 프레임워크 뼈대 (시작 전)
- **활성 작업**: 없음 (Phase 0 첫 작업 지시 대기)

## 활성 worklog

없음. Phase 0 작업이 시작되면 Claude Code가
`docs/worklog/<YYYY-MM-DD>-phase0-<slug>.md` 를 만든다.

## 최근 커밋

```
2202434 docs: pivot to framework-first architecture with plugin model
9ad6e88 docs: lock central server stack and add git auto-commit convention
c0f67f9 feat: base structure
```

## 지금 멈춘 위치

설계 문서·ADR 작성과 framework pivot까지 완료. 코드는 한 줄도 작성 안 함.
다음 단계는 Phase 0 코어 뼈대 구현(`docs/roadmap.md` Phase 0 체크리스트).

## 다음 한 걸음

다음 Claude Code 세션 시작 시 이 절차를 그대로 따른다:

1. `/CLAUDE.md`, `docs/design.md`, `docs/roadmap.md`, `docs/decisions/` 전체,
   `docs/plugins.md` 를 읽고 framework-first 모델을 머리에 박는다.
2. `docs/worklog/2026-MM-DD-phase0-skeleton.md` 를 새로 만들고 `TEMPLATE.md` 에
   따라 작성 시작.
3. `pyproject.toml` 의 `dependencies` 를 `docs/design.md §11` 에 적힌 예정 목록으로
   채운다(`fastapi`, `uvicorn[standard]`, `httpx[http2]`, `pydantic`,
   `pydantic-settings`, `structlog`, `typer`, `sqlalchemy[asyncio]`, `aiosqlite`,
   `alembic`, `python-ulid`, `keyring`, `pynacl`).
4. `pip install -e ".[dev]"` 가 깨끗하게 끝나는지 확인.
5. 거기서 멈추고 첫 체크포인트(워크로그 + STATUS.md + git commit) 마무리.

## 블로킹 / 결정 필요

- 없음 (Phase 0 시작에 필요한 결정은 다 봉인됨).
- Phase 1 진입 전 ADR-0003(distribution) 갱신 필요. 지금은 무시 가능.

## 진행 게이지

- [x] 설계 문서 v0.1 작성
- [x] framework pivot v0.2
- [x] ADR-0001 ~ 0007 봉인 (0004 superseded)
- [ ] Phase 0 코어 뼈대 구현
- [ ] Phase 1a 플러그인 SDK
- [ ] Phase 1b 보안 경계 강화
- [ ] Phase 1c scope_guard 플러그인
- [ ] Phase 2+ (Mode R sink, 협업자 plugin)

---

## 갱신 규칙 (Claude Code용)

매 체크포인트에 다음을 한 단위로 처리한다 (CLAUDE.md §3 체크포인트 규칙):

1. 코드 변경을 git commit (CLAUDE.md §9 규칙).
2. 활성 worklog 의 "한 일" 섹션에 그 commit 해시를 적는다.
3. 본 STATUS.md 의 다음 항목을 갱신한다:
   - 최종 업데이트 (YYYY-MM-DD)
   - 활성 worklog
   - 최근 커밋 3–5개
   - 지금 멈춘 위치
   - 다음 한 걸음

이 셋을 묶어 처리하지 않으면 세션 cutoff 시 다음 세션이 길을 잃는다.
