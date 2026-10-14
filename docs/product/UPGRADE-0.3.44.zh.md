# Universal Browser 0.3.44 升级说明

## 列表导航同源 iframe

- 录制「从列表页搜索进详情」时会在**同源 iframe** 内监听点击，并记录 `frame_index`。
- 模板 `run.list_navigation` 写入 `search_*_frame_index` / `row_link_frame_index`；运行期解析 ref 与 label 时按帧匹配。
- 开始录制时若存在跨域 iframe，控制台会提示无法录制其内部（与点选模式一致）。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.44/universal-browser-full-0.3.44.zip
```
