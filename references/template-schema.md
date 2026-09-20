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

The host Agent platform renders template selection and variable collection. Template files must not
contain platform-specific UI component identifiers.
