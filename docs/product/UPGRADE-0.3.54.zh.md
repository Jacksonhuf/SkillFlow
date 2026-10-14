# Universal Browser 0.3.54 升级说明

## Webhook 批量重试建议

- `delivery.webhook` 在批量运行完成时，`batch` 对象除 `stats` 外新增 **`retry_suggestions`**。
- 每项为可直接调用的 `retry_batch` 元数据：`run_id`、`failure_bucket`、`value_count`、`values_sample`（最多 10 条）。
- 与 0.3.53 `retry-batch` CLI / `retry_batch` 动作配套，便于回调服务按桶自动重跑。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.54/universal-browser-full-0.3.54.zip
```
