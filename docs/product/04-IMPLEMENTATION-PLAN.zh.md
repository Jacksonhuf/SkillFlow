# 实施计划 — 按阶段交付

状态标记：✅ 已完成　🔄 进行中　⬜ 待做

## 阶段 0：架构基线（PR #18 → 本 PR 合并）

- ✅ Template 2.0 schema（processing / analysis / report / delivery）
- ✅ Learned Profile 分离存储
- ✅ 采集策略规划器
- ✅ manifest.json / pipeline.json
- ✅ 架构文档 `docs/PLATFORM-ARCHITECTURE.zh.md`

## 阶段 A：本地界面（Agent + Skill 主入口配套）

- ✅ `console/server.py`：本机 HTTP API（令牌、后台任务、运行历史、制品下载、doctor、通用 action）
- ✅ `console/ui.html`：单页界面（模板 / 运行记录 / Teach / 环境）
- ✅ `invoke.py ui` 与 `browser-skill ui` 子命令
- ✅ 单元测试：令牌、模板列表、任务执行、制品下载越界

## 阶段 B：业务闭环（Process → Report → Deliver）

- ✅ processing：`rename_field` / `dedupe_records` / `coerce_type` / `default_value`
- ✅ report：`report.md` 生成
- ✅ delivery：`local` 目录投递、`webhook` JSON 通知（失败不阻断运行）
- ✅ analysis：占位上下文写入 pipeline.json
- ✅ 单元测试覆盖

## 阶段 C：触发与分发

- ✅ Windows 任务计划脚本 `skill-scripts/windows/Register-ScheduledRun.ps1`（打包为 `scripts/windows/`）
- ✅ SKILL.md / references / STANDALONE 文档更新（`ui` 命令与本机界面说明）
- ✅ 完整包体积门禁保持 ≤5MB（当前 78 文件，约 120KB）

## 验证记录（本 PR）

| 项 | 结果 |
|----|------|
| `pytest` 全量 | 160 通过、1 跳过（integration） |
| `mypy --strict` | 通过 |
| `ruff` | 仅遗留 `snapshot_normalize.py` 一处 E501（main 已有） |
| 控制台真实浏览器渲染 | Headless Chrome 打开 `/?token=` 正常显示模板卡片 |
| 后台任务 | Fake 适配器 run → COMPLETED，生成 `report.md` / `manifest.json` / `pipeline.json` |

## 阶段 D：稳定采集

- ✅ 适配器 `network` 能力与 `network_requests()`（CLI `network list --json` / 平台工具 `network.list` / Fake）
- ✅ Teach 阶段读取已发生的 XHR/Fetch，匹配模板字段（含 camelCase / 别名 / 语义），写入 `preferred_source: network` + `endpoint_hint` + `json_path`
- ✅ Run 阶段 Network 优先采集（仅允许主机），缺失自动回退 DOM 并记录事件
- ✅ Teach → Test 闭环测试：学到端点后测试运行直接使用 JSON 记录
- ✅ 分页模板的 Network 采集：`NetworkRecordSource` 作为 `RecordExtractor.collect` 的按页记录来源，翻页（下一页 / 加载更多 / 滚动 / 页码）仍由 DOM 驱动，每页只读取新出现的 JSON 响应，无新响应的页自动回退 DOM 表格；事件记录 `network_pages` / `dom_pages`
- ✅ Playwright 适配器 `browser/playwright_adapter.py`（`BrowserAdapter` 全协议）：CDP 附着到用户已登录 Chrome / 独立持久 Profile / 临时实例三种模式；快照输出交互元素 `@eN` 引用与表格 `columnheader`/`cell`（含 `row_index`/`column_index`）；`find` 多策略定位并跳过禁用控件；下载、弹窗（自动关闭 + 状态上报）、多标签、XHR/Fetch JSON 响应捕获（`network_requests`）
- ✅ 引擎切换：`browser/factory.py`，`invoke.py --engine playwright` 或 `UNIVERSAL_BROWSER_ENGINE=playwright`；`UNIVERSAL_BROWSER_CDP_URL` / `UNIVERSAL_BROWSER_PROFILE_DIR` / `UNIVERSAL_BROWSER_CHROME_PATH` / `UNIVERSAL_BROWSER_HEADLESS`
- ⬜ Vision 兜底接口

### 阶段 D 验证记录

| 项 | 结果 |
|----|------|
| `pytest` 全量 | 171 通过、1 跳过（Network 非分页） |
| `mypy --strict` | 通过 |
| 新增用例（Network 非分页） | 解析多种请求形态、发现端点忽略非允许主机、必填字段缺失不学习、提取与回退、无能力不调用 |
| 新增用例（分页 Network） | 按页只读新响应、翻页两页均走 Network、Network + DOM 混合页 |
| Playwright 集成测试 | 本地站点 + 无头 Chrome：快照表格/引用、翻页、网络捕获、下载、弹窗、填表；Runner 端到端两页 Network 采集；无学习映射时 DOM 表格回退（无 Playwright/Chrome 时自动跳过） |

## 阶段 E：智能化与运营（后续 PR）

- ⬜ 样例对齐 Teach（自动比对上传样例与试跑结果）
- ⬜ 异常 AI 摘要（由 Host Agent 调用模型）
- ⬜ 邮件 / 企业微信分发适配器
- ⬜ 模板权限与多用户审计（若引入服务端）

## 里程碑验收

| 里程碑 | 判定 |
|--------|------|
| M1 界面可用 | 界面完成一次运行并下载制品 |
| M2 闭环可用 | 2.0 模板生成 report.md 且本地投递成功 |
| M3 定时可用 | 任务计划触发 `invoke.py run` 成功 |
| M4 稳定采集 | 同一模板在改版后通过 Repair 恢复 |
