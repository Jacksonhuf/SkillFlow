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

## 本地界面（可选，同一引擎）

- 用户希望「用界面操作」时，告知运行 `py scripts\invoke.py ui`，浏览器自动打开 `http://127.0.0.1:8765/?token=...`。
- 界面里的运行、Teach、续跑与 Agent 调用的是同一套 `BrowserSkillApp`，`run_id` 与 `runs/` 产物互通；Agent 可直接引用界面产生的 `run_id`。
- 界面仅本机可访问，不要把带 token 的链接发给他人。

## 成功后的产物（2.0 模板）

- 除 `result.*` 外还有 `manifest.json`（记录+附件包）、`report.md`（若启用 `report`）、`pipeline.json`（各阶段状态，含 `deliver.channels` 投递结果）。
- 投递失败不影响 run 成功；向用户汇报时读取 `pipeline.stages.deliver` 说明哪个渠道未送达。

## Network 采集（自动，无需用户参与）

- Teach `discover` 的 JSON 里有 `network` 字段：`learned: true` 表示已学到 JSON 端点，之后运行会优先读该端点；`enabled: false` 表示当前 chrome-use 不支持网络监听，走 DOM 采集即可。
- 运行事件 `network_extraction` / `network_extraction_fallback` 出现在 `execution.jsonl`；回退到 DOM 不是错误。分页模板同样适用：翻页由页面驱动，每页优先读新 JSON 响应，事件里的 `network_pages` / `dom_pages` 说明各页来源。
- 不要向用户解释 XHR / endpoint / json_path，这些属于 Learned Profile 内部细节。

## 浏览器引擎（运维设置，Agent 不需要提示用户）

- 默认 chrome-use。运维可通过 `--engine playwright` 或环境变量 `UNIVERSAL_BROWSER_ENGINE=playwright` 切换为 Playwright 驱动本机 Chrome（`UNIVERSAL_BROWSER_CDP_URL` 附着已登录 Chrome，或独立持久 Profile）。
- 两种引擎的返回契约（状态、`run_id`、产物）完全一致；Agent 执行流程不因引擎而变化。

## 与附件相关

- 模板声明 `attachments` 时，运行前会检查 chrome-use 是否具备 **find + download + downloads**。
- 定位顺序：snapshot `elements` → 语义 `find` → `download` 到 run 工作区。
- snapshot 若为 `interactive`/`nodes` 等字段，引擎会自动归一化为 `elements`。
