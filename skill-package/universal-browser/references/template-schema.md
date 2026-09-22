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

The host Agent platform renders template selection and variable collection. Template files must not
contain platform-specific UI component identifiers.
