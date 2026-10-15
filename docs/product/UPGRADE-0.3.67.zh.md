# Universal Browser 0.3.67 升级说明

## 已发布模板：Fork 后改 Webhook

- `update_delivery` 支持 **`fork_as_new_version`** / CLI **`--fork`**：从指定已发布版本复制出下一版 **草稿**，写入新的 Webhook/报告开关，**不修改**原发布 YAML。
- 控制台对已发布任务展示分发面板，按钮「复制为新版本并保存分发」。
- 响应含 **`forked_from_version`** 与新 **`version`**，须试跑后再 `publish`。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.67/universal-browser-full-0.3.67.zip
```
