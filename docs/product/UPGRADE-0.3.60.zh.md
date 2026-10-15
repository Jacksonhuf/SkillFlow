# Universal Browser 0.3.60 升级说明

## Webhook 共享密钥

- `delivery.webhook` 的 channel `options.webhook_secret`（或 `secret`）会在 POST 时附带请求头 **`X-Universal-Browser-Webhook-Secret`**。
- 示例 `webhook_retry_listener.py` 支持环境变量 **`UNIVERSAL_BROWSER_WEBHOOK_SECRET`** 校验（未设置则不鉴权）。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.60/universal-browser-full-0.3.60.zip
```
