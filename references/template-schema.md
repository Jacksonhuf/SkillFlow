# Template schema quick reference

Use `schema_version: "1.0"`. Keep `template_id` stable and version-independent. Use machine-stable
keys for fields and attachments; use `name` for display. Declare a `record_key` for pagination,
detail traversal, and attachment association.

Templates contain: identity/status, system scope, auth signals, variables, target fields and
attachments, typed workflow hints, non-sensitive learned mappings, validation rules, and output
settings. Validate every loaded file with `BrowserTemplate`.

Never persist passwords, OTPs, cookies, tokens, authorization headers, current snapshot refs, or
screen coordinates. Never relax target/variable/output/validation contracts during Repair.

See `templates/inventory_feedback/1.yaml` for a complete example and
`docs/template-schema.md` for the normative field reference.

## Schema 2.0 additions

- Optional `processing` / `analysis` / `report` / `delivery` sections (business pipeline stages).
  - `analysis`: `enabled`, `compare_with_previous` (record-count swing vs. the last completed run),
    `record_change_threshold` (default 0.5), `prompt_template` / `model_hint` for a host model.
  - `delivery.channels[]`: `type` in `local | webhook | email | wecom`, `target` (directory, URL,
    or comma-separated recipients), `options` (`subject`, `attach`, `max_attachment_mb`,
    `title`, `attach_result`, `mentioned_mobile_list`). SMTP credentials come from
    `UNIVERSAL_BROWSER_SMTP_*` environment variables, never from the template.
- Field extras: `aliases`, `validation_rule`. Attachment extras: `aliases`, `match_by`, `multiple`,
  `min_size_bytes`, `max_size_bytes`.
- Learned mappings for 2.0 templates are stored beside the contract in
  `templates/<id>/learned/<version>.yaml`; the business YAML never carries site internals.
- `LearnedMapping.preferred_source` selects the acquisition ladder rung (`api`, `network`, `dom`,
  `browser`, `vision`). For `network`, Teach records `endpoint_hint` (URL path on an allowed host)
  and `json_path` (`$.data.list[*].orderNo`); Run reads the browser's observed JSON exchange first
  and falls back to DOM/table extraction when the exchange is missing.

## URL batch (detail_batch) templates

- `run.mode: detail_batch` runs one detail page per value of `run.driver_variable`; the default
  `run.mode: list` keeps the classic single-entry workflow. Other `run` knobs: `concurrency`,
  `per_item_delay_ms`, `on_item_error` (`continue | stop`), `dedupe_values`, `max_items`,
  `accept_full_urls`, `capture_tables`.
- `system.url_template` is an absolute http(s) URL with `{variable}` placeholders (never in the
  host part); its host must be in `allowed_hosts` and every placeholder must be a declared
  variable. Values are URL-encoded when rendered.
- The driver variable must set `multiple: true`. Multi-value input accepts a JSON array or text
  split on newlines / commas / semicolons. A value that is itself a full `http(s)` URL is opened
  directly (when `accept_full_urls`), skips the variable regex, and still has to pass the
  `allowed_hosts` policy check.
- `filename_pattern` placeholders for attachments: any record field key (the driver value is
  always stamped on each record) and `{original_name}`.
- Runtime: after the login check on `entry_url` the Runner opens each planned URL in turn
  (`per_item_delay_ms` with ±30% jitter between items), extracts one record per page (or one
  per table row with `capture_tables`), downloads the declared attachments, and records the
  item in `runs/<run_id>/batch.json` (`pending | ok | partial | failed`, `reason`, `error`).
  A record missing a required field, or a required attachment that did not download, marks
  the item `failed` and keeps it out of the result; optional gaps mark it `partial`. Any
  failed item makes the run `PARTIAL` with `summary.items.failed_values`; `on_item_error: stop`
  fails the run at the first failure; all items failing is a `FAILED` run. If a detail page
  shows the login screen the run pauses in `WAIT_USER_AUTH` and `resume` continues with the
  first unfinished item. Events: `item_started`, `item_finished`, `item_failed`,
  `item_deferred`, `batch_finished`. `concurrency` is accepted but items currently run
  sequentially.

The host Agent platform renders template selection and variable collection. Template files must not
contain platform-specific UI component identifiers.
