# Universal Browser 0.3.63 升级说明

## 向导：可选 Webhook 分发

- 新建模板向导「高级设置」可填写 **Webhook URL** 与 **共享密钥**；保存草稿时写入模板 `delivery.webhook`（含 `options.webhook_secret`）。
- `ProbeDraftInput` 新增 `webhook_url` / `webhook_secret`，`create_from_probe` 与控制台向导一致。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.63/universal-browser-full-0.3.63.zip
```
