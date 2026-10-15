# Universal Browser 0.3.56 升级说明

## 批量运行结果：重试建议

- `run` / `test` / `retry_batch` 完成且为批量模式时，响应 `data.retry_suggestions` 与 Webhook / 控制台运行详情一致（含 `cli` 一行命令示例）。
- 无失败项时不附带该字段，避免噪音。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.56/universal-browser-full-0.3.56.zip
```
