# Template Schema 1.0

## Conventions

- Reject unknown keys (`extra="forbid"`).
- Use stable lowercase snake-case machine keys and localized display names.
- Keep `template_id` independent of `version`.
- Store no secret or ephemeral element reference.

## Top-level fields

| Field | Type | Rule |
|---|---|---|
| `schema_version` | literal `1.0` | Required |
| `template_id` | string | `^[a-z][a-z0-9_]{2,63}$` |
| `name` | string | Human-facing, non-empty |
| `description` | string | Short menu explanation |
| `status` | enum | draft/testing/published/degraded/disabled |
| `version` | integer | ≥1 |
| `system` | object | entry URL and allowed host scope |
| `auth` | object | reuse strategy and semantic signals |
| `variables` | map | Name to typed variable definition |
| `target` | object | record key, fields, attachments, pagination |
| `workflow` | object | Typed, policy-checked hints |
| `learned` | object | Stable tested hints only |
| `validation` | object | Immutable business success contract in Repair |
| `output` | object | json/csv/xlsx/both/files-only and safe patterns |

## Variables

Supported types are `string`, `integer`, `number`, `boolean`, `date`, and `enum`. Defaults may use
`today` or `yesterday` for dates. Regex, min/max, and enum options are declarative. `sensitive` only
controls redaction; it never permits credential collection.

## Targets

Fields have `key`, `name`, `type`, `required`, semantic aliases, and `source` (`list`/`detail`). The
target declares one or more field keys as `record_key` when record association is required.

Attachments have stable key/name, required flag, semantics, source, per-record flag, allowed file
types, safe filename pattern, destination subdirectory, and optional maximum count.

Pagination strategies are `none`, `next_button`, `page_number`, `load_more`, and `infinite_scroll`.
Button/load-more modes declare semantic controls; all modes have a bounded maximum page count, and
load-more/infinite-scroll use a bounded unchanged-page idle count.

Workflow hints may include an optional `dom_hint` only as a validated CSS selector or XPath. It is
used after learned/Snapshot semantics and semantic `find` fail. Script strings, coordinates, live
snapshot refs, and raw page instructions are invalid template data.

## Validation and output

Validation can require complete fields, complete pagination, required downloads, a minimum/maximum
record count, and unique record keys. Output supports `json`, `csv`, `xlsx`, `both`, and
`files-only`. `both` means JSON plus CSV. XLSX strings are stored as inline data cells so values
beginning with formula characters are never evaluated as formulas. Patterns interpolate only known
sanitized values.

Generate the machine-readable schema with:

```bash
browser-skill schema > template.schema.json
```
