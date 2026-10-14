# Universal Browser 0.3.47 升级说明

## 平台契约：Teach 推荐能力

- `fixtures/platform/minimum-contract.json` 增加 `recommended_operations`（点选、列表导航、展开录制、`network.list`）与推荐能力 `network`。
- `probe-platform` / `action=probe` 报告 `missing_recommended_operations`，**不阻断** `ready`（与推荐 capability 一致），便于 Host 插件补齐向导能力。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.47/universal-browser-full-0.3.47.zip
```
