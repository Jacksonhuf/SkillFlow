# Universal Browser 0.3.30 升级说明

## 控制台并行批量进度

- 并行 `detail_batch` 时，任务进度会跟踪**多条进行中**的编号（`progress.active`），文案显示「并行 N 路（M 条进行中）」。
- 若运行时声明并行但适配器不支持 `batch_page`，会明确报错，不再静默跳过该项。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.30/universal-browser-full-0.3.30.zip
```
