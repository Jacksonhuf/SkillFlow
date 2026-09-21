# Internal platform acceptance — authorized environment only

This document is the release boundary between repository-verifiable behavior and behavior that can
only be proven inside the company's authorized Agent platform. Nothing in the local Fake Adapter
suite is evidence that this gate passed.

## Preconditions

- A non-production enterprise test tenant and least-privilege test account.
- The internal Agent platform can install this Skill and inject its structured `chrome-use` tool.
- The chrome-use extension/native bridge is online in the tester's real Chrome profile.
- An allowlisted test site provides a list, a detail page, pagination, and a harmless attachment.
- The test owner has approved collection and retention locations for generated artifacts.

Do not place passwords, OTPs, cookies, authorization headers, or production business data in test
requests, screenshots, templates, logs, or issue reports.

## Contract probe

Record the platform and plugin versions, then verify that the injected tool supports `status`,
`capabilities`, `open`, interactive/diff `snapshot`, `find`, `click`, `fill`, `download`,
`downloads`, tab operations, and dialogs. A missing required capability fails acceptance; it must
not be silently replaced with browser scripting or a second automation framework.

## Required scenarios

1. **Menu and variables:** render template cards and required-variable fields with usable text
   fallback and keyboard-accessible actions.
2. **Authenticated extraction:** reuse an existing signed-in Chrome session, query the test site,
   parse at least two list records, visit one detail record, and merge a declared detail field.
3. **Attachment:** download one declared attachment beneath the Run workspace, verify nonzero size
   and allowed extension, and associate it with the expected business key.
4. **Human authentication:** expire the session, observe `WAIT_USER_AUTH`, complete login/MFA in
   Chrome without sending credentials to the Agent, and resume the same `run_id`.
5. **Pagination:** traverse at least two pages and prove the expected record count and no duplicate
   business keys.
6. **Repair:** change a harmless test-page label, fail the published mapping, perform one Repair,
   pass the full Test Run, publish the immutable next version, and link the original failed Run.
7. **Cancellation and recovery:** cancel a paused Run and confirm that the terminal state is durable.
8. **Security review:** inspect template YAML, `run.json`, JSONL events, summaries, output data, and
   platform logs; confirm that no credential, Cookie, authorization header, OTP, or snapshot ref was
   persisted.

## Evidence bundle

Store only redacted evidence approved by the test owner:

- environment/plugin versions and capability response;
- scenario IDs, template ID/version, Run IDs, timestamps, and terminal states;
- redacted `summary.json` and execution-event schema samples;
- expected versus actual record/download counts;
- auth pause/resume and Repair/recovery linkage;
- reviewer names, date, defects, retest results, and final sign-off.

The release gate passes only when every required scenario has explicit evidence and no unresolved
high-severity security or correctness defect. This repository intentionally does not provide a way
to mark that external gate as passed from local tests.
