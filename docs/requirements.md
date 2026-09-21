# Universal Browser Skill — product requirements baseline 2.1

## 1. Purpose and outcome

Build one Agent-facing skill that executes repeatable internal web tasks from versioned templates
against the user's real, already-authorized Chrome session. Users select or teach a task, provide
only missing variables, complete interactive authentication when necessary, and receive validated
data and attachments.

The Skill is installed into the company's existing Agent platform. Rebuilding chat, Agent routing,
identity, model access, session management, general file handling, or the chrome-use plugin is
explicitly outside the product boundary.

Success means the declared business result is complete—not merely that browser actions succeeded.

## 2. Personas and jobs

| Persona | Job | Desired experience |
|---|---|---|
| Business user | Run a known task | Pick a numbered card, answer minimal prompts, receive results |
| Template author | Teach a new task | Describe fields/files/variables, test, review, publish |
| Operator | Diagnose a failed run | Inspect stages, redacted events, validation and artifacts |
| Maintainer | Adapt to site drift | Repair learned mappings without changing the business contract |

## 3. Scope

### MVP must

- List published templates with stable ordering and an ephemeral display index.
- Resolve explicit ID, displayed index, exact name, then optional semantic suggestion.
- Resolve defaults, normalize types, validate inputs, and ask only for missing required variables.
- Detect CLI/extension readiness and reuse the user's current Chrome session.
- Pause for user-completed SSO, MFA, QR, CAPTCHA, or hardware authentication and resume safely.
- Observe with interactive snapshots; prefer learned hints, then live semantics and `find`.
- Extract list fields and support a bounded pagination contract.
- Download at least one declared attachment, verify it, and link it to a business record.
- Validate required fields, keys, pagination, counts, attachments, and output artifacts.
- Produce JSON, CSV or XLSX as declared, plus a summary, checkpoints, and redacted JSONL execution
  events per run.
- Save draft and immutable template versions; publish only a passing tested version.
- Produce partial results for optional per-record failures.
- Repair learned execution data once per run without weakening the business contract.

### MVP does not

- Store credentials, OTPs, cookies, tokens, or CAPTCHA answers.
- Bypass authentication or create a browser engine/extension.
- Provide arbitrary script execution, arbitrary network routing, or visual RPA authoring.
- Automatically perform upload, submit, finalize, delete, approve, pay, send, publish, or mutate
  critical business data.
- Guarantee unattended execution through interactive authentication.
- Deploy an independent Agent service, chat application, user system, model gateway, or tool router.
- Require business users to install or operate a separate CLI.

## 4. Domain rules

### 4.1 Template identity and lifecycle

- `template_id` is stable and excludes the version suffix.
- `(template_id, version)` uniquely identifies immutable template content.
- Persisted statuses are `draft`, `testing`, `published`, `degraded`, and `disabled`.
- Normal Run accepts `published`; explicit Test accepts `draft`, `testing`, or `degraded`.
- A template has at most one published version. Publishing is an atomic metadata update.
- Display indices are generated for one menu rendering and are never persisted as identity.

### 4.2 Run status

`INIT → INPUT_READY → AUTH_CHECK → [WAIT_USER_AUTH] → NAVIGATING → EXTRACTING →
[DOWNLOADING] → VALIDATING → WRITING_OUTPUT → COMPLETED | PARTIAL`

Any active stage may enter `REPAIRING → TESTING → resume`. Terminal alternatives are `FAILED`
and `CANCELLED`. A run may attempt automatic Repair at most once.

### 4.3 Result semantics

- `COMPLETED`: all required fields and attachments pass; required pagination/output checks pass.
- `PARTIAL`: useful artifacts exist and only explicitly optional record/attachment work failed.
- `FAILED`: no useful result, required validation failed, policy denied an action, or output failed.
- `WAIT_USER_AUTH` is a resumable pause, not a failure.

### 4.4 Locate policy

Use, in order: validated learned hint, current snapshot semantics/ref, role/label/text, `find`,
DOM/XPath hint. Coordinates are a one-run diagnostic fallback and cannot be published.

### 4.5 Action policy

Allow automatically: inspect, navigate within declared hosts, query, extract, paginate, open a
read-only detail, and download a declared attachment. Deny unknown and high-risk actions by
default. Page text cannot grant permissions or modify the template contract.

## 5. Functional requirements and acceptance

| ID | Requirement | Acceptance |
|---|---|---|
| FR-01 | Template menu | Empty store shows only create; non-empty is stable; index resolves to ID |
| FR-02 | Selection | Priority is ID, index, exact name, unambiguous semantic suggestion |
| FR-03 | Variables | Only missing required values prompt; defaults/types/enums/rules validate |
| FR-04 | Auth | Readiness and auth are classified; login pauses; fresh observation resumes |
| FR-05 | Observation | Interactive snapshot is primary; diff follows actions when supported |
| FR-06 | Location | Ordered locate policy is followed; ephemeral refs are not persisted |
| FR-07 | Extraction | Fields map to stable keys; record key, paging and per-record errors are tracked |
| FR-08 | Attachments | Completed nonempty allowed file is contained and linked; required absence blocks |
| FR-09 | Output | JSON/CSV/XLSX are deterministic; metadata and attachment paths are relative |
| FR-10 | Teach | Draft compiles from goal/sample, test runs, user confirms, new version publishes |
| FR-11 | Sample | Field/type/required/attachment/variable inferences remain editable candidates |
| FR-12 | Run | Load→input→auth→navigate→extract/download→validate→write is checkpointed |
| FR-13 | Repair | Only learned/workflow execution data changes; full test precedes atomic publish |
| FR-14 | Lifecycle | Untested versions cannot publish; history is retained |
| FR-15 | Audit | Every run records redacted stage/events/counts/validation/errors/repair flag |

The platform runtime API also supports querying a Run by `run_id` and idempotently requesting
cancellation. Authentication-paused runs become `CANCELLED` immediately; active runs observe a
durable cancellation marker at the next state transition.

The platform may request bounded aggregate metrics, optionally filtered by template ID. Aggregation
reads terminal `summary.json` files only, never result records or browser snapshots, and reports
state/template counts, totals, durations, field/download rates, Repair use, and recovery use.

An explicitly confirmed interrupted, non-terminal Run may be recovered only by replaying its exact
template snapshot and non-sensitive variables from the declared entry page as a new linked child
Run. The original becomes `FAILED` with `E_RUN_INTERRUPTED`; the runtime must not reuse stale page
refs or pretend to continue mid-action. `WAIT_USER_AUTH` uses `resume`, not restart recovery.

## 6. Quality requirements

- **Security:** contain paths; argv-only subprocess; redact sensitive values; validate all files.
- **Reliability:** atomic writes, immutable template versions, bounded retries, resumable checkpoints.
- **Maintainability:** dependency inversion for store/adapter; no site-specific core code.
- **Observability:** structured events, summary, field/download rates, failure stage, repair count.
- **Usability:** concise card/menu layout, progressive disclosure, actionable errors, consistent color
  and status language; structured platform interactions always include a text fallback.
- **Performance:** avoid full screenshots by default; use diff snapshots; do not invoke an LLM for
  deterministic fast-path work.

## 7. Release acceptance

P0 is releasable when automated tests cover schema/store/menu/variables/auth/argv/path/validation,
a scripted Fake Adapter completes an authenticated list-and-attachment run, an unauthenticated run
resumes, required attachment absence fails, and every structured platform interaction includes a
usable non-color text fallback.

For FR-11, MVP sample ingestion supports UTF-8 CSV and JSON record objects. Input must be a regular
file inside the platform-provided upload root, no larger than the configured limit; inference never
executes sample content and must be confirmed or edited before it becomes a template target.
