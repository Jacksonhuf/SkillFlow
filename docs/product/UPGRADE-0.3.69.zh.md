# Universal Browser 0.3.69 升级说明

## 模板多版本

- **`TemplateStore.version_history`**：`browser-skill template-versions <id>`、`py scripts/invoke.py versions <id>`、`browser-skill templates --json`。
- 控制台 **`GET /api/templates/:id/versions`**；详情支持 **`?version=`**；运行面板多版本时下拉切换。
- 便于在 fork 出草稿后选择正确 `version` 做 `update-delivery` / 试跑。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.69/universal-browser-full-0.3.69.zip
```
