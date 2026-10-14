# Universal Browser 0.3.48 升级说明

## Playwright Teach 能力声明

- Playwright 引擎的 `capabilities_payload.operations` 声明点选、列表导航、展开录制与 `network.list` 等向导所需操作。
- `doctor` / 探针在 **local_cli** 下也会根据 `operations` 报告 `missing_recommended_operations`（无 operations 时不误报）。
- 控制台「技术详情」摘要会提示缺失的推荐 capability / teach 操作数量。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.48/universal-browser-full-0.3.48.zip
```
