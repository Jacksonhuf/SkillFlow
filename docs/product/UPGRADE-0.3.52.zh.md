# Universal Browser 0.3.52 升级说明

## Webhook 分发：批量统计

- `delivery.webhook` 的 JSON 在 `detail_batch` 运行完成时会附带 `batch` 对象：`driver_variable` 与完整 `stats`（含 `failure_groups`、`list_navigation_failure_values`、`pick_field_empty_values`）。
- 便于外部调度/告警按原因触发重跑或通知。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.52/universal-browser-full-0.3.52.zip
```
