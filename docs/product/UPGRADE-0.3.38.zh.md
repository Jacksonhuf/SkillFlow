# Universal Browser 0.3.38 升级说明

## 批量历史：按原因重跑

- 「历史结果」打开批量 run 时，会**重新计算** `batch.stats`（含 `failure_groups`、`pick_field_empty_values`），旧 run 也能看到分类。
- 每一类失败/部分成功（如 **点选字段为空** `pick_field_empty`）可单独 **重跑**；明细表支持按原因筛选。
- 运行完成页增加「重跑点选空列」按钮（含 partial 项）。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.38/universal-browser-full-0.3.38.zip
```
