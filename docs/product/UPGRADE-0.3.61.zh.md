# Universal Browser 0.3.61 升级说明

## chrome-use：`operations` 声明

- 本地 chrome-use 适配器的 `capabilities_payload` 现包含 **`operations`**（Teach 录制类为 `false`，`network.list` 随 `network` 能力）。
- `doctor` / 控制台环境检测在 **local_cli** 下会正确列出 `missing_recommended_operations`，与 Playwright 行为一致。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.61/universal-browser-full-0.3.61.zip
```
