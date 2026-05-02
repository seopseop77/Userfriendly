# ADRs (Architecture Decision Records)

Records of decisions that are hard to reverse or wide in impact. Naming:
`NNNN-<kebab-slug>.md` (NNNN = 4-digit incrementing number).

## When to write an ADR

- Adding or replacing a dependency.
- Changing a public interface (CLI, env vars, event schema, DB schema).
- Changing the deployment or hosting model.
- Changing a security or privacy boundary.
- Any decision that, two weeks from now, would prompt a "wait, why is it
  like this?".

Smaller implementation choices belong in the worklog (`../worklog/`).

## Status values

- `Proposed`: drafted, not yet sealed.
- `Accepted`: in force, the project follows it now.
- `Superseded by NNNN`: replaced by another ADR.
- `Deprecated`: no longer applies; kept for historical record.

When an ADR needs revising, **don't overwrite it** — write a new ADR that
supersedes it. The history of reasoning is preserved.

Template: `TEMPLATE.md`.
