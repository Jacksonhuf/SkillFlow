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

## 批量模板（`run.mode: detail_batch`）

`start` / 模板列表里 `run.mode == "detail_batch"` 的模板，是「给一批编号（或详情页地址），逐条打开详情页取字段和附件」。

- **收集一组值，而不是单值。** 驱动变量（`run.driver_variable`，`multiple: true`）接受多个值：
  - 重复 `--var`：`run <id> --var order_no=ORD-1 --var order_no=ORD-2`
  - 从文件读一列：`run <id> --var-file orders.csv --var-column 订单号`（`.txt` 一行一个；CSV/TSV/XLSX 首行为表头，`--var-column` 填列名或 1 起的序号，默认第 1 列；`--var-name` 可指定非驱动变量）
  - 用户在对话里粘贴的多行 / 逗号分隔文本也可以直接作为一个 `--var` 值传入（会自动拆分）。
  - 值也可以是完整详情页 URL（`accept_full_urls`），host 必须在模板 `allowed_hosts` 内。
- **读结果时看 `data.items`**：`{total, ok, partial, failed, skipped, failed_values}`；每项明细在 `runs/<run_id>/batch.json`。`skipped` 是模板开了 `run.skip_if_exists`（增量）时、此前已成功采集而本次未访问的编号（`reason: done_in:<run_id>`），它们的数据在那次运行的产物里，不算失败。
  - `state == PARTIAL` 且 `failed_values` 非空：如实告知哪些编号失败（`batch.json` 里有 `reason`，如 `E_PAGE_NOT_FOUND`、`required_field_missing:*`），并可**只重跑失败项**：把 `failed_values` 作为新的 `--var` 值再次 `run`。
  - `on_item_error: stop` 的模板在第一条失败就结束；`error.details.items` 里同样有进度。
- **登录过期**：批量中途 `WAIT_USER_AUTH` 时，用户在 Chrome 登录后 `resume <run_id>`，已完成的项不会重跑。
- 不要为了「更快」自行并发或改写 URL；`per_item_delay_ms` / `concurrency` 由模板决定。

## 用一个网址新建批量模板（`probe`）

- `py scripts\invoke.py probe <详情页URL>` 返回 `data.probe`：`url_analysis`（哪段是变量、建议的 `url_template`）、`fields`（字段候选：key / 名称 / 示例 / 来源 url·dom·table·network / 置信度 / `recommended`）、`attachments`（附件候选）、`warnings`。
- 降噪规则：只有页面上可见的值（URL 变量、页面「标签：值」、表格列、与页面同值的接口字段）`recommended: true`；仅存在于接口返回里的值 `recommended: false`。接口的 `code/msg/total/pageSize/traceId` 等信封字段、与本条记录无关的响应（菜单、当前用户、字典）不会出现在候选里。向用户展示时**默认只列 recommended 的字段**，其余作为「更多候选」按需展示。
- 未登录时 `ok: false`、`interaction.actions` 只含 `retry_probe_url`：让用户在打开的 Chrome 登录后重试同一命令。
- `data.probe.tables`：页面上的多行表格（记录行候选），每个含 `index`、`title`、`headers`、`columns`（列候选，含 `key/name/sample/type/column`）、`row_count`、`preview`（前 3 行）、`recommended`（有表头且 ≥2 行）。两列的「标签 | 值」表不会出现在这里（已并入页面字段）。
- 让用户确认要保留的字段 / 附件和主键后，调用 `create_from_probe`（请求体 `probe_draft`：`template_id`、`name`、`sample_url`、`url_template`、`driver_variable`、勾选的 `fields`、`attachments`、`record_key`、`required_keys`），再 `test` 若干编号，`COMPLETED` 后 `publish`。
- 要抓**表格的每一行**（明细行、付款记录等）时，在 `probe_draft` 里加 `table: {index, title, headers, columns: [勾选的列]}`（直接取自 `data.probe.tables[i]`，`columns` 只保留需要的列）。生成的模板 `run.capture_tables: true`，每一行输出一条记录，自动带上页面字段和 `row_no`（行号，主键之一）；附件仍按页面下载一次。`fields` 可为空（只要表格行）。列 key 与页面字段 key 不能重名。
- 业务用户更适合在本地界面「新建模板」里完成同样三步（探测 → 勾选 → 试跑/发布）。

## 本地界面（可选，同一引擎）

- 用户希望「用界面操作」时，告知运行 `py scripts\invoke.py ui` 或双击 `open-console.bat`，浏览器打开 `http://127.0.0.1:8771/`（仅本机，无 token）。
- 界面里的运行、Teach、续跑与 Agent 调用的是同一套 `BrowserSkillApp`，`run_id` 与 `runs/` 产物互通。
- 界面仅绑定 127.0.0.1，不要暴露到公网或代理到外网。

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

## 样例比对 / 分析 / 分发（读取结果即可，不需要额外操作）

- Teach 阶段用户上传过样例时，`test` 请求带上 `sample_path`，返回的 `data.sample_alignment` 给出覆盖率与中文差异清单（`issues`）；`aligned: false` 时先把差异告诉用户再决定是否 publish。
- `pipeline.json` 的 `stages.analyze` 含 `severity`（ok / info / warning / error）、`summary`、`findings`；向用户汇报时直接引用 `summary`（若有 `ai_summary` 优先）。校验失败的运行也有该字段（在错误 details 与 `pipeline.json` 中）。
- `stages.deliver.channels` 逐渠道给出 `ok` 与 `error`（local / webhook / email / wecom）；分发失败不影响运行成功，只需如实告知哪个渠道未送达。

## 与附件相关

- 模板声明 `attachments` 时，运行前会检查 chrome-use 是否具备 **find + download + downloads**。
- 定位顺序：snapshot `elements` → 语义 `find` → `download` 到 run 工作区。
- snapshot 若为 `interactive`/`nodes` 等字段，引擎会自动归一化为 `elements`。
