# Universal Browser Skill — test strategy and acceptance plan 2.1

## 1. Quality strategy

Use a test pyramid: pure domain unit tests; structured interaction contract tests; scripted
FakeBrowserAdapter component scenarios; platform-tool adapter contract tests; optional diagnostic
CLI tests; and opt-in real chrome-use integration tests. No CI test may depend on a user's browser.

## 2. Requirement traceability

| Requirement | Primary automated evidence |
|---|---|
| FR-01/02 | menu ordering and selector precedence tests |
| FR-03 | default/type/enum/missing/sensitive variable tests |
| FR-04 | auth classifier and pause/resume fake scenarios |
| FR-05/06 | adapter argv, snapshot sequence and no-ref persistence tests |
| FR-07 | table records, keys, duplicates and pagination scenarios |
| FR-08 | completed/missing/empty/type/path/per-record download tests |
| FR-09 | deterministic JSON/CSV/XLSX, formula safety and artifact containment tests |
| FR-10/11 | draft compiler and publish guard tests |
| FR-12 | state transition and full happy-path component test |
| FR-13/14 | frozen-contract diff, test gate and immutable version tests |
| FR-15 | redaction, event shape, count and repair flag tests |

Platform integration additionally verifies that template menus, variable forms, auth pauses,
progress, and results remain UI-framework-neutral and include accessible text fallbacks.

## 3. Critical scenarios

1. **Happy path:** published template, valid default date, authenticated snapshot, two records,
   attachment completed, validation passes, JSON/CSV/summary produced.
2. **Authentication pause:** login signal produces `WAIT_USER_AUTH`; a subsequent authenticated
   observation resumes without collecting variables again.
3. **Required field missing:** useful records exist but a required value is absent; Repair is
   attempted once, then the run fails if still invalid.
4. **Optional attachment missing:** output is retained and status is `PARTIAL`.
5. **Required attachment missing:** status is `FAILED`; never `COMPLETED`.
6. **Pagination loop:** repeated page fingerprint or page budget terminates with incomplete paging.
7. **Site drift:** learned hint fails, semantic candidate works, full test passes, new immutable
   version is published.
8. **Unsafe filename:** traversal and reserved characters are sanitized/contained.
9. **Prompt injection:** snapshot instructions requesting shell/high-risk actions are ignored.
10. **CLI incompatibility:** missing/unsupported capability fails before navigation.
11. **Teach lifecycle:** create returns a review interaction and the next immutable version while the
    current published version remains active.
12. **Publish evidence:** missing confirmation, unsafe Run ID, mismatched version, `PARTIAL`, and
    missing summary are rejected; only exact `COMPLETED` evidence publishes.
13. **Repair candidate:** learned data changes in a new testing version while target, variables,
    auth, output, and validation remain identical.
14. **Sample inference:** CSV/JSON fields, types, optional cells, attachment/variable/key candidates,
    nested JSON values, unsupported formats, size limits, symlinks, and path traversal are covered.
15. **Mapping discovery:** authenticated snapshots map declared semantics, missing required targets
    block candidate creation, and snapshot refs/coordinates never appear in persisted templates.
16. **Run control:** status returns accessible progress, paused runs cancel immediately, active runs
    observe durable cancellation, terminal cancellation is idempotent, and unsafe Run IDs fail.
17. **Detail records:** each list record opens its matching detail, verifies identity, merges detail
    fields, downloads and associates detail attachments, then returns to a refreshed list snapshot.
18. **Snapshot tables:** accessibility headers/cells and row cell collections become records through
    declared field semantics; undeclared columns remain untrusted and are ignored.
19. **Automatic Repair:** a failed Run gets one discovery attempt; the frozen contract is exercised
    by a full child Test Run, only a completed test publishes the immutable version, and the original
    Run stores its recovery Run ID. Failed repair returns the original Run to `FAILED`.
20. **Teach exploration:** only declared page/detail semantics are actionable, traversal is bounded,
    every observed URL remains inside the allowlist, list/detail mappings remain source-correct, and
    no ephemeral target is persisted.
21. **Interrupted Run recovery:** confirmation is mandatory, terminal/auth-paused/cancelled Runs are
    rejected, stale refs are never reused, the original is finalized with an interruption summary,
    and a new child Run replays the exact template from its entry point.
22. **Terminal observability:** success and failure summaries contain duration, state durations,
    checkpoints, counts, pagination, validation/error, Repair attempts, and recovery linkage.
23. **Locator priority:** learned snapshot hint wins, then exact/partial declared semantics, then
    semantic `find`; record scoping is preserved, ambiguity/missing targets are repairable failures,
    and workflow navigation cannot escape allowed hosts.
24. **Metrics:** aggregation is bounded and optionally template-filtered, ignores malformed/symlinked
    summaries, reads no result records, and returns accessible state/count/rate information.
25. **Pagination strategies:** next button, page number, load more, and infinite scroll obey page/idle
    budgets; cycles and unchanged next-page clicks are incomplete, and cross-host snapshots fail.
26. **CLI boundary:** metacharacters remain one argv value, sensitive fill/type values are redacted
    from safe diagnostics, and DOM fallback accepts selectors/XPath but rejects scripts/coordinates.
27. **Dialog/readiness safety:** resume reprobes the extension and Snapshot capability; an unexpected
    post-click browser dialog is dismissed and fails safely rather than being implicitly accepted.
28. **XLSX output:** the OOXML ZIP parses, strings remain inline non-formulas, XML controls are
    removed, numeric/boolean types remain native, names stay contained, and sheet bounds fail safely.

## 4. Non-functional tests

- **Security:** path traversal, symlink escape, argv metacharacters, secret redaction, unknown YAML,
  undeclared action and host escape.
- **Reliability:** subprocess timeout/kill, malformed output, interrupted atomic write cleanup,
  duplicate run workspace, confirmed interrupted replay, and bounded polling while a download is
  still in progress.
- **Usability:** text fallback at 80 columns, actionable error and empty state, and no dependence on
  color or platform-specific widgets.
- **Platform UX:** stable action IDs, structured choices, text fallback, no CLI-only instruction,
  and resumable auth interaction carrying the original `run_id`.
- **Performance:** bounded command count; diff snapshots after first observation; a 10k-row fixture
  exercises validation plus deterministic JSON/CSV generation without quadratic duplicate checks.

## 5. Test commands and gates

```bash
pytest
ruff check .
mypy src/browser_skill
python /opt/codex/skills/.system/skill-creator/scripts/quick_validate.py .
browser-skill doctor                # optional local diagnostic, not a user workflow
pytest -m integration               # internal platform release environment only
```

Merge gate: unit/component/CLI tests and lint/type checks pass. Release gate additionally requires
the internal platform's chrome-use plugin contract, extension, signed-in test account, allowed test
site, one extraction, one download, one auth pause/resume, artifact delivery, and confirmation that
no sensitive value was persisted.

The authoritative external procedure and evidence bundle are defined in
`docs/internal-platform-acceptance.md`; local tests can never mark that gate passed.
