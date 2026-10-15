# Webhook 按桶自动重试（示例）

## 前提

- 模板 `delivery.channels` 含 `type: webhook`，目标 URL 指向你的接收端。
- 批量运行结束后，POST 体含 `event: run_finished` 与 `batch.retry_suggestions`（0.3.54+）。
- 可选：在 channel `options.webhook_secret` 配置共享密钥；运行时会 POST 头 `X-Universal-Browser-Webhook-Secret`。示例监听器用环境变量 `UNIVERSAL_BROWSER_WEBHOOK_SECRET` 校验。

## 内置示例监听器

在技能根目录（含 `SKILL.md`）：

```bash
# 仅回显 suggestions（不自动跑浏览器）
py scripts/examples/webhook_retry_listener.py --port 9876

# 自动对每个 suggestion 调用 invoke retry-batch
export UNIVERSAL_BROWSER_WEBHOOK_AUTO_RETRY=1
export UNIVERSAL_BROWSER_WEBHOOK_RETRY_BUCKETS=list_navigation,pick_field_empty
py scripts/examples/webhook_retry_listener.py --port 9876
```

模板 webhook 目标示例：`http://127.0.0.1:9876/`（生产请用 HTTPS 与鉴权）。

## 自建服务

Python：

```python
from browser_skill.pipeline.webhook_retry import extract_webhook_retry_suggestions, filter_retry_buckets

suggestions = filter_retry_buckets(
    extract_webhook_retry_suggestions(payload),
    allowed_buckets={"list_navigation"},
)
```

对每条 suggestion 调用 `retry_batch`（HTTP 技能 API）或 `py scripts/invoke.py retry-batch <run_id> --bucket <bucket>`。

## 注意

- 自动重试会再次打开 Chrome 并占用与正常 `run` 相同的队列；建议按 `failure_bucket` 限流。
- 监听器默认只绑定 `127.0.0.1`；勿在未鉴权的情况下暴露到公网。
