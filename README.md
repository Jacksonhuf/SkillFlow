# Universal Browser Skill

A platform-native Skill package for template-driven browser tasks. It installs into an existing
Agent platform, uses that platform's chrome-use tool/plugin with the user's signed-in Chrome, treats
downloads as first-class outputs, and reports success only after business-result validation.

It is **not** an Agent platform, standalone chat application, browser automation service, or end-user
CLI. The host platform owns conversation, identity, model access, sessions, file delivery, user
confirmation, and UI rendering.

## Integration outline

```bash
Internal Agent Platform
  └── installs this Skill
      ├── loads SKILL.md and templates
      ├── calls deterministic Python helpers where supported
      └── injects its existing chrome-use tool invoker
```

Production integration uses `ChromeUseToolAdapter`, which maps the stable `BrowserAdapter` protocol
to the host platform's structured chrome-use tool calls. `ChromeUseAdapter` and the
`browser-skill` command are optional developer diagnostics for environments that expose a local CLI;
business-user workflows must not depend on them.

## Interaction model

1. In the existing Agent conversation, pick a published template or create a draft.
2. Supply only missing required variables.
3. Complete SSO, MFA, QR, CAPTCHA, or hardware authentication directly in Chrome when prompted.
4. Receive JSON/CSV/XLSX as declared, downloaded files, a validation report, and a concise summary.

Teach and Repair always create a reviewable, non-published version. Publishing requires explicit
user confirmation plus a `COMPLETED` Test Run for that exact template ID and version.

Teach can derive editable target candidates from a bounded UTF-8 CSV or JSON sample supplied through
the platform's upload workspace; sample content is parsed as data and never executed.

After authentication, bounded Mapping discovery matches declared target semantics against a fresh
snapshot and writes a new testing version only when every required target is found. Ephemeral
element refs and coordinates are never stored.

The Skill returns UI-neutral template menus, variable forms, authentication pauses, progress, and
result objects. The platform renders them using its native chat/cards/forms and text fallbacks.
Every terminal Run emits a metrics-rich summary. A confirmed interrupted worker is recovered by
starting a linked child Run from the immutable template entry point rather than reusing stale page
references; authentication pauses continue through the original Run's resume action.
Runtime actions share an ambiguity-safe learned/snapshot/find Locator. The platform can also request
bounded cross-Run metrics derived only from terminal summaries, without reading business records.
Design, development, and test specifications live in [`docs/`](docs/); Agent operating guidance
lives in [`SKILL.md`](SKILL.md).

Production release additionally requires the authorized internal-platform procedure in
[`docs/internal-platform-acceptance.md`](docs/internal-platform-acceptance.md). Fake Adapter tests
deliberately cannot mark that external gate as passed.

## Maintainer setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev,cli]'
pytest
browser-skill doctor  # optional local CLI compatibility check
```

## Safety defaults

- Automatic actions are limited to read, navigate, query, extract, and template-declared download.
- Submit, delete, approve, pay, send, publish, upload, and business-data mutation are denied unless
  a future policy explicitly adds human confirmation support.
- Template paths and downloaded filenames are contained within the run workspace.
- Secrets are redacted from events, and browser element refs are never persisted in templates.
