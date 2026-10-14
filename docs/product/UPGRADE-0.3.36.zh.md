# Universal Browser 0.3.36 升级说明

## 批量可观测性

- 点选字段（`dom_hint`）在单条采集后仍为空时，该项记为 **partial**，原因 `pick_field_empty:<字段 key>`（必填点选字段仍会导致 **failed**）。
- `batch.json` / 运行响应中的 `items.failure_groups` 按原因前缀汇总失败与部分成功的编号，控制台「历史结果」与运行完成页展示分类摘要。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.36/universal-browser-full-0.3.36.zip
```
