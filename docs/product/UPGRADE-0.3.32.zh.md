# Universal Browser 0.3.32 升级说明

## Pick Mode（点选字段）

- 新建 URL 批量模板 → 步骤 2 → **开始点选字段**：在 Chrome 中点击要采集的页面值（可多次），**结束点选** 后字段会加入列表并写入 `dom_ref`（`@eN`），运行时按 `dom_hint` 定位。
- 需要 **Playwright** 引擎；chrome-use 会提示不支持。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.32/universal-browser-full-0.3.32.zip
```
