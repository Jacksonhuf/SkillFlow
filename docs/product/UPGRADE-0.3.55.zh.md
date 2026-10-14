# Universal Browser 0.3.55 升级说明

## 控制台：与 CLI/Webhook 一致的批量重跑

- 试跑/运行结果与「历史结果」中的 **按原因重跑** 按钮改为调用 **`retry_batch`**（从 `batch.json` 解析编号，继承原运行的非驱动变量）。
- 运行详情 API 的 `batch` 增加 **`retry_suggestions`**（与 Webhook 0.3.54 字段一致），便于自建 UI 对接。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.55/universal-browser-full-0.3.55.zip
```
