# Universal Browser 0.3.68 升级说明

## 模板 inspect JSON

- **`browser-skill inspect <id> --json`** 与 **`py scripts/invoke.py inspect <id>`** 输出与控制台 `/api/templates/:id` 同形的契约 JSON（含 `delivery_channels`，不含密钥明文）。
- 人类可读 `inspect` 增加运行模式、流水线与分发摘要。

## 清除 Webhook 密钥

- `update_delivery` 支持 **`clear_webhook_secret`** / CLI **`--clear-webhook-secret`**；控制台勾选「清除已保存的 Webhook 密钥」。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.68/universal-browser-full-0.3.68.zip
```
