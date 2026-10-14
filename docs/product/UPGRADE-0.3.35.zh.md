# Universal Browser 0.3.35 升级说明

## Pick Mode 运行期回退

- 点选字段学习时会保存 `pick_sample`（点选时的样本文本）。
- 详情页 SPA 重渲染导致快照 `@eN` 编号变化时，运行期会按样本文本在同帧元素中回退匹配，减少空列。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.35/universal-browser-full-0.3.35.zip
```
