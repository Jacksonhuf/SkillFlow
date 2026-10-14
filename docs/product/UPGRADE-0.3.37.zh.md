# Universal Browser 0.3.37 升级说明

## Pick Mode：结束点选后刷新快照

- 「结束点选」后会自动拍摄一次交互快照，并按样本文本把 `@eN` **对齐到当前快照**（SPA 重绘导致编号变化时更稳）。
- Playwright 快照会收录页面上已标记 `data-ubs-ref` 的点选元素，批量运行期更容易按 ref 取值。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.37/universal-browser-full-0.3.37.zip
```
