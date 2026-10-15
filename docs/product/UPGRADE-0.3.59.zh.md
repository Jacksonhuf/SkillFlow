# Universal Browser 0.3.59 升级说明

## Webhook 自动重试示例

- 新增 `scripts/examples/webhook_retry_listener.py`：接收 `delivery.webhook` POST，解析 `batch.retry_suggestions`，可选自动调用 `invoke.py retry-batch`（`UNIVERSAL_BROWSER_WEBHOOK_AUTO_RETRY=1`）。
- 库函数 `pipeline/webhook_retry.py` 供自建服务复用。
- 独立包 `invoke.py` 增加 **`retry-batch`** 子命令（与 `browser-skill retry-batch` 一致）。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.59/universal-browser-full-0.3.59.zip
```
