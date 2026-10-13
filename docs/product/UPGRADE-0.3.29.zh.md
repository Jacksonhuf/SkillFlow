# Universal Browser 0.3.29 升级说明

## 批量并发（Playwright）

- 模板 `run.concurrency` 设为 **2–4** 时，在 **Playwright** 引擎下会并行打开多个标签页处理 `detail_batch` 项（同一浏览器上下文，共享登录态）。
- `execution.jsonl` 会记录 `concurrency_parallel`（含 `configured` / `effective`）。
- **chrome-use** 适配器仍按单页串行执行；`concurrency > 1` 时继续记录 `concurrency_sequential`。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.29/universal-browser-full-0.3.29.zip
```
