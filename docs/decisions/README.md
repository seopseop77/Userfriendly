# ADR (Architecture Decision Records)

되돌리기 어렵거나 영향 범위가 넓은 결정을 기록한다. 파일명 규칙:
`NNNN-<kebab-slug>.md` (NNNN = 4자리 증분).

## 언제 ADR을 쓰는가

- 새 의존성 추가/교체
- 공개 인터페이스(CLI, 환경변수, 이벤트 스키마, DB 스키마) 변경
- 배포/호스팅 방식 변경
- 보안/프라이버시 경계 변경
- "2주 뒤의 우리가 '왜 이렇게 되어 있지?' 하고 물을 만한" 결정

구현 수준의 사소한 선택은 워크로그(`../worklog/`)로 충분하다.

## 상태

- `Proposed`: 작성했지만 확정 전
- `Accepted`: 확정, 지금 이 프로젝트가 따르는 결정
- `Superseded by NNNN`: 다른 ADR이 대체함
- `Deprecated`: 더는 해당하지 않지만 기록 목적으로 남김

ADR을 수정할 때는 **내용을 덮어쓰지 않고** 새 ADR을 만들어 대체(supersede)한다.
과거 추론 흐름을 지우지 않기 위함.

템플릿은 `TEMPLATE.md`.
