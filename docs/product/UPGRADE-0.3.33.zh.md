# Universal Browser 0.3.33 升级说明

## Pick Mode 运行期修复与增强

- 点选字段（`dom_ref` / `@eN`）在批量运行时会从快照元素中读取文本，不再只靠「标签：值」猜测。
- 同源 iframe 内点选会记录 `frame_index`；学习映射写入 `learned.frame_index`。
- 中文标签字段默认生成 `ref_eN` 形式 key；向导字段列表显示「点选」标记。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.33/universal-browser-full-0.3.33.zip
```
