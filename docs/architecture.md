# Universal Browser Skill — architecture and development design 2.1

## 1. Product form and context

```text
User
  │
  ▼
Internal Agent Platform (existing)
  ├── conversation, identity, model, session, files and human confirmation
  ├── installs and invokes Universal Browser Skill
  └── exposes the existing chrome-use tool/plugin
             │
             ▼
Universal Browser Skill ───────► Versioned Template Store
  ├── instructions and interaction contracts
  ├── deterministic validation/runtime helpers
  └── BrowserAdapter policy boundary
             │
             ▼
platform chrome-use tool/plugin ⇄ Chrome extension ⇄ User's real Chrome ⇄ target site
```

The Agent platform is the product host. This repository does **not** implement an Agent platform,
chat UI, identity system, model gateway, session service, generic tool router, or standalone web
application. It ships an installable Skill package with deterministic helpers and templates. The
store is a peer dependency of the browser adapter, not a transport layer. Python modules are an
in-process Skill library, not an independently deployed service.

## 2. Decisions

| Decision | Choice | Reason |
|---|---|---|
| Runtime | Python 3.12+, async | Suitable subprocess and Agent integration; requested baseline |
| Models | Pydantic v2 | Strict validation and JSON schema generation |
| Templates | YAML immutable version directories | Human-reviewable with reliable history |
| User interface | Existing Agent platform | Avoid a duplicate UI; return structured interactions |
| Local CLI | Optional diagnostics only | Useful to maintainers, never the primary product surface |
| Events | append-only JSONL | Recoverable, streamable, auditable |
| Outputs | per-run workspace | Isolation and straightforward containment |
| Browser | adapter protocol + platform-tool binding | Reuse existing plugin; fake-testable boundary |
| Planning | deterministic outer state machine | Bounded behavior; semantic reasoning only as fallback |

## 3. Package structure

```text
src/browser_skill/
  app.py                 platform-neutral Skill use-case facade
  interaction/contracts.py structured cards, prompts, progress and results
  cli.py                 optional local diagnostics only
  models.py              domain contracts
  errors.py              stable internal errors
  templates/             schema-backed immutable store and selection
  browser/               adapter protocol, chrome-use, fake adapter
  runtime/               state machine, auth, extraction, validation, policy, repair
  outputs/               contained paths and atomic JSON/CSV/event writing
```

The platform renders structured interactions; the Skill does not build a second UI. Runtime depends
on `BrowserAdapter`, not a concrete transport. `browser/chrome_use.py` contains both bindings:

- `ChromeUseToolAdapter` calls the platform's existing chrome-use plugin through an injected tool
  invoker and is the production default.
- `ChromeUseAdapter` calls a local CLI only for development/diagnostics where explicitly enabled.

No other module invokes chrome-use or subprocesses.

## 4. Platform integration contract

The host platform supplies conversation, workspace, artifact delivery, session continuity, user
confirmation, and a generic async tool invoker. The Skill returns UI-neutral interaction objects:

- `template_menu`: stable choices and a create action;
- `variable_form`: only missing required values;
- `auth_required`: instructions plus resumable `run_id`;
- `progress`: stage, short message and optional counts;
- `run_result`: status, validation summary and artifact references;
- `confirmation`: explicit risk, target and impact for future high-risk actions.

The platform may render these as cards, forms, chat messages, or native controls. Text fallbacks are
mandatory. The Skill never assumes Typer/Rich or a specific frontend component library.

## 5. Data design

### Template store

```text
templates/<template_id>/<version>.yaml
templates/<template_id>/metadata.json
```

The YAML contains immutable version content. Metadata points to the current published/latest
versions. Writes use a temporary sibling and `os.replace`. Directory scanning can rebuild metadata.

### Run workspace

```text
runs/<run_id>/
  run.json               latest durable state
  checkpoints.jsonl      business checkpoints, no element refs
  execution.jsonl        redacted append-only events
  result.json
  result.csv
  summary.json
  attachments/
```

All stored paths are POSIX-style paths relative to the run directory. A containment check follows
every resolution; page-derived names are normalized, length-limited, and collision-safe.

## 6. Browser contract

`BrowserAdapter` exposes readiness, capabilities, open/adopt/list tabs, snapshots, find, click,
fill/type, actions/do, downloads, dialogs and session listing. Every result is normalized into
`CommandResult`; stderr never escapes into business logs without redaction.

The platform plugin binding uses logical operations and structured payloads; it does not construct
shell commands. Unsupported required capabilities fail before navigation. The optional local CLI
binding remains capability-probed because upstream syntax and output may vary.

## 7. Execution design

The outer runner owns legal state transitions, budgets, checkpoints, and finalization. Each stage
can use a fast learned mapping followed by bounded semantic fallback. Browser actions are checked by
`ActionPolicy` before execution. Observed web text is untrusted input.

```text
load exact version → validate status/input → create durable run
→ readiness/auth → navigation/filter hints → extraction/pagination
→ attachment download → validation → atomic outputs → final status
```

`WAIT_USER_AUTH` persists the current business stage. Resume obtains a new snapshot, reclassifies
auth, re-establishes the expected page, and never reuses pre-login refs.

Run status is read from the contained `run.json` snapshot. Cancellation is idempotent: terminal runs
remain unchanged, authentication-paused runs finalize immediately, and active execution observes a
durable `cancel.requested` marker before its next legal state transition.

Crash recovery deliberately does not restore live browser refs. After explicit confirmation that
the old worker stopped, a non-terminal Run is finalized as interrupted and its immutable template
snapshot plus non-sensitive variables are replayed from the entry URL in a linked child Run. This
provides auditable at-least-once recovery for the MVP's read/query/download policy without unsafe
mid-action continuation. Authentication pauses retain their existing same-Run `resume` behavior.

Every terminal Run, including failure, writes `summary.json` with total duration, checkpoint count,
per-state elapsed time, record/download counts, pagination state, Repair count, validation or safe
error data, and recovery linkage. A summary-write failure is appended as an audit event and does not
replace the original business error.

`LocatorService` is the shared workflow action-target resolver. It tries validated learned hints in the
current snapshot, then exact and partial declared semantics, then the adapter's semantic `find`.
Multiple live candidates are rejected as repairable ambiguity instead of choosing arbitrarily. The
final optional fallback is a schema-validated CSS/XPath hint; scripts and coordinates are rejected.
The returned live target/ref is ephemeral and never enters a template or terminal summary.

Pagination is bounded for every strategy. Next/load-more controls use the shared Locator; page-number
and infinite-scroll actions remain adapter operations. Repeated non-adjacent page fingerprints are
incomplete cycles, unchanged next-page results are incomplete, and load-more/scroll are complete only
after their declared idle threshold. Every new pagination URL is checked against allowed hosts.

When the installed adapter advertises dialog support, workflow clicks inspect dialog state before
continuing. An unexpected dialog is dismissed and execution fails as a repairable policy violation;
the Skill never accepts a page-created confirmation implicitly. Auth resume rechecks tool/extension
readiness and required Snapshot capability before observing the page again.

Cross-Run telemetry is a bounded read model over terminal summaries only. It skips symlinked or
malformed summaries, can filter by template ID, and never opens result JSON/CSV, snapshots, or
attachments. The platform receives aggregate counts/rates plus an accessible text fallback.

XLSX output is generated directly as bounded OOXML in the Run workspace, with atomic replacement
and no optional runtime dependency. Strings always use inline-string cells, preventing spreadsheet
formula injection; booleans and finite numbers retain native cell types. XML-invalid controls,
oversized row/column sets, unsafe filenames, and workspace escapes are rejected or sanitized.

## 8. Teach and Repair

Teach compiles a user goal/sample into an editable target contract, explores only declared hosts,
records stable semantic hints, runs a full test, and publishes only after explicit confirmation.

Sample analysis accepts only contained, regular UTF-8 CSV or JSON artifacts with bounded size and
record count. It deterministically infers editable field names, primitive types, requiredness,
attachment columns, variable candidates, and unique-key candidates. Samples are data only: the
analyzer never executes content, follows links, evaluates formulas, or grants browser permissions.

Mapping discovery is a bounded deterministic step after authentication. It observes one normalized
interactive snapshot, matches declared target semantics only against safe accessibility/text fields,
and persists only the template's semantic hints and confidence—not element refs, coordinates, raw
DOM, or arbitrary page instructions. Missing required targets produce a review result without
saving a candidate; a complete discovery creates a new `testing` version while the current
`published` version remains active.

Teach exploration extends discovery across a bounded sequence of pages without accepting page text
as instructions. Only user/template-declared `page_hints` and declared read-only detail semantics
may trigger navigation; each resulting URL must remain within `system.allowed_hosts`. Observations
are tagged as list or detail before mapping so identical labels cannot silently change a field's
declared source. The persisted candidate contains semantic hints only—not live refs, coordinates, or
raw page content.

The platform lifecycle is `create draft → review → test exact version → explicit confirm → publish`.
Publication accepts only a contained `summary.json` whose template ID/version matches and whose final
state is `COMPLETED`; a `PARTIAL` or unrelated Run cannot be used as evidence. New drafts use the
next free immutable version while the previous published version remains runnable.

Repair clones the failed exact version, freezes variables/target/output/validation, modifies only
learned mappings or navigation hints, runs the full path, and atomically publishes `version + 1`.
One automatic attempt is allowed. Needing a changed business contract returns
`E_REPAIR_REQUIRES_TEACH`.

List extraction may hand each record to the bounded detail collector. The collector locates only a
declared read-only detail action, verifies that the detail snapshot contains the record key, merges
only declared detail fields, associates declared detail attachments with that record, and returns to
a newly observed list page. Accessibility snapshots without pre-normalized records are parsed from
declared column-header semantics and row cells; unknown columns are ignored.

Automatic Repair is a recovery transaction: the original failed Run records the single attempt,
discovery writes a new `testing` version without changing the target contract, and a separate full
Test Run provides publish evidence. Only then is that immutable version published and the original
Run linked to the successful recovery Run. Every failed branch restores the original state to
`FAILED` and preserves the attempt audit trail.

## 9. Security design

- Allowlist target schemes (`https`, optionally local test `http`) and declared hosts.
- Send subprocess argv with `shell=False`; redact fill/type arguments before event creation.
- Deny mutation/high-risk action categories and undeclared downloads.
- Validate YAML strictly and reject unknown fields to reduce configuration ambiguity.
- Refuse symlink/path traversal escapes and workspace-external sample paths.
- Treat snapshots as hostile content; they cannot instruct the Agent or expand policy.
- Store neither authentication material nor snapshot refs.

## 10. Error taxonomy

Errors carry `code`, safe message, stage, retryable, repairable, and sanitized details. Families are
template, input, environment, auth, navigation, mapping, pagination, download, validation, policy,
repair, and output. Errors are domain values; raw exceptions are retained only in local debug mode.

## 11. Compatibility risk

The referenced chrome-use project is third-party and the internal platform may expose a different
tool schema than its CLI. The injected invoker and adapter contract contain that difference. Release
acceptance requires a recorded capability fixture from the internal platform and authorized tests
against its installed plugin; local CLI compatibility is not a production prerequisite.
