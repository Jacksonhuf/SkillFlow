# Development and verification loop

Each increment follows the same loop:

1. Select requirement IDs and state observable acceptance criteria.
2. Add or update domain contracts before implementation.
3. Write failing unit/component tests with a scripted fake adapter.
4. Implement the smallest safe vertical slice.
5. Run focused tests, then the complete quality gate.
6. Review security, accessibility, logging, compatibility, and documentation impacts.
7. Demonstrate through the platform interaction contract; run real-browser integration only in an
   authorized internal platform test environment.

The primary demonstration surface is the internal Agent platform. The local CLI is limited to
developer diagnostics; no requirement may depend exclusively on it.

## Delivery slices

| Slice | Requirements | Deliverable |
|---|---|---|
| 0 | external dependency | platform contract fixture, probe CLI/app action, capability report |
| 1 | FR-01–04, 09, 15 | models/store/menu/variables/auth/workspace/events |
| 2 | FR-05–09, 12 | bounded Runner, extraction/download/validation/outputs |
| 3 | FR-10–11, 14 | draft compiler, test/publish gate |
| 4 | FR-13–15 | frozen-contract Repair and immutable new version |

Definition of Done includes tests, type/lint checks, no sensitive persistence, documentation and
error messages, Fake Adapter acceptance, and real integration evidence before production release.

## Current implementation cycle

- Delivery slice 0 (platform contract fixture, structured probe, acceptance bundle validator): complete in-repo.
- Platform-hosted product boundary and structured interaction contract: complete.
- Structured chrome-use tool adapter and Fake Adapter contract tests: complete.
- Teach draft creation, immutable next-version allocation, exact-version Test evidence, explicit
  publish confirmation, and Repair candidate creation: complete.
- Bounded CSV/JSON sample analysis and editable target-review interaction: complete.
- Authenticated single-page semantic Mapping discovery with no snapshot-ref persistence: complete.
- Durable Run status, idempotent cancellation, and cancellation checks at transitions: complete.
- Per-record detail navigation, detail-field merge, detail attachment association, and safe return
  to the list: complete with Fake Adapter coverage.
- Accessibility Snapshot table parsing, including semantic header mapping: complete.
- One-shot automatic Repair, immutable testing version, full-path Test Run, publish gate, and
  recovery linkage to the original failed Run: complete with Fake Adapter coverage.
- Bounded multi-page Teach exploration driven only by declared page/detail semantics, host policy,
  and an explicit action budget: complete with Fake Adapter coverage.
- Terminal success/failure metrics, asynchronous download completion polling, subprocess/atomic-write
  fault injection, 10k-record output validation, and confirmed interrupted-Run replay as a linked
  child: complete.
- Deterministic learned/snapshot/find Locator priority with ambiguity rejection and bounded,
  summary-only cross-Run metrics exposed through a platform interaction: complete.
- All declared pagination strategies, idle/cycle/page budgets, pagination host checks, optional versus
  required attachment end states, argv injection resistance, and sensitive CLI redaction: complete.
- Resume readiness revalidation and safe rejection/dismissal of unexpected browser dialogs: complete.
- Dependency-free atomic XLSX output with native number/boolean types, formula-injection resistance,
  XML sanitization, spreadsheet bounds, and archive validation: complete.
- Template Store directory, version, and metadata paths reject symlinks and malformed version pointers
  before reading, publishing, or writing template content: complete.
- Internal-platform real-browser acceptance remains the only environment-bound release gate; it
  requires the platform's actual chrome-use fixture and authorized enterprise account and follows
  `docs/internal-platform-acceptance.md`. Use `browser-skill probe-platform`, Skill action `probe`,
  and `browser-skill validate-acceptance` to prepare and verify the evidence bundle structure after
  authorized manual scenarios complete.
