# Universal Browser 0.3.45 升级说明

## 批量失败：列表导航分组重试

- 列表搜索/进详情失败时，`batch.json` 的 `reason` 记为 `list_navigation:<错误码>`（如 `list_navigation:element_not_found`）。
- 控制台历史与进度里的 **按原因重试** 可单独选中「列表搜索/进详情」失败项。

## 展开点击录制提示

- 开始录制附件展开步骤时，若页面含跨域 iframe，向导会提示无法在其内部录制（与点选/列表导航一致）。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.45/universal-browser-full-0.3.45.zip
```
