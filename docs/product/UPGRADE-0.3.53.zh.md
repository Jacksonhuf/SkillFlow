# Universal Browser 0.3.53 升级说明

## 按原因重跑批量项（API / CLI）

- 新动作 **`retry_batch`**：`run_id` 指先前批量运行，可选 `failure_bucket`（`failed`、`pick_field_empty`、`list_navigation` 或任意 `failure_groups` 键）。
- 从 `runs/<run_id>/batch.json` 解析驱动值并启动新运行；响应 `data.retry_batch` 记录来源与编号列表。
- CLI：`retry-batch <run_id> [--bucket list_navigation]`（与控制台「按原因重跑」一致，便于 Webhook 回调后自动重试）。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.53/universal-browser-full-0.3.53.zip
```
