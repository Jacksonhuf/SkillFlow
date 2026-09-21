# Repository completion status

This file tracks completion against `docs/requirements.md` 2.1 and the delivery slices in
`docs/development-plan.md`.

## Automated repository gates — complete

| Gate | Evidence |
|---|---|
| FR-01 … FR-15 behavior | 125 pytest cases across unit/component/integration suites |
| Merge quality | `ruff check .`, `mypy src/browser_skill`, `python scripts/quick_validate.py` |
| CI | `.github/workflows/ci.yml` on push/PR |
| Slice 0 contract fixture | `fixtures/platform/minimum-contract.json` |
| Platform probe | Skill action `probe`, `browser-skill probe-platform`, `browser-skill doctor` |
| Acceptance bundle shape | `browser-skill validate-acceptance`, action `validate_acceptance` |
| Integration hook | `pytest -m integration` (live chrome-use optional via env var) |

## External release gate — operator-owned

Authorized internal-platform scenarios in `docs/internal-platform-acceptance.md` require a real
Agent host, enterprise test account, and signed-in Chrome. After those scenarios pass, attach a
JSON evidence bundle and run:

```bash
browser-skill validate-acceptance evidence.json --require-sign-off
```

No local test can mark that external gate as passed without the authorized environment.

## Default branch

Production code lives on `main` after merge from feature branches. The historical `codex` branch
contained the first full implementation drop.
