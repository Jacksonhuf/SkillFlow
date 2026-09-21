# Agent 执行契约（OpenCode / Skill Hub）

## 必须

1. 所有浏览器结果来自 **`py scripts\invoke.py`**（或 `invoke.bat`），不得用对话「假装已抓取」。
2. 流程：`start`（或已知 template_id 时直接）→ `run <template_id> --var ...` → 需要时 `resume <run_id>`。
3. 向用户汇报成功时，必须附带 **`run_id`** 与 `runs/<run_id>/` 下产物路径（来自 JSON 的 `artifacts`）。
4. 附件只认模板 `AttachmentDownloader` 输出；禁止在聊天里手工拼下载链接充当附件。

## 禁止

- 跳过模板，自行「读页面 / 注入 JS / 用其它浏览器工具」抽取。
- 让用户安装 chrome-use CLI、运行 `doctor`、配置 `CHROME_USE_BIN`。
- 向业务用户展示 `probe`、daemon、snapshot 格式等运维术语；失败时读 JSON 的 `error.details`，对用户只说业务语言或「请稍后重试」。

## 失败时 Agent 怎么做

1. 读 `invoke run` 的完整 JSON（`error.code`、`error.details.missing_capabilities` 等）。
2. 可静默重试一次 `run`（网络/扩展瞬时离线）。
3. 仍失败：对用户简短说明；运维根据 `error.details.operator_guide` 或 `invoke capabilities` / `doctor` 处理。

## 与附件相关

- 模板声明 `attachments` 时，运行前会检查 chrome-use 是否具备 **find + download + downloads**。
- 定位顺序：snapshot `elements` → 语义 `find` → `download` 到 run 工作区。
- snapshot 若为 `interactive`/`nodes` 等字段，引擎会自动归一化为 `elements`。
