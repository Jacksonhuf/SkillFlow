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
- ✅ Vision 兜底接口：`acquire/vision.py` 定义 `VisionProvider`（由 Host 注入视觉模型）与 `VisionFallback`（截图 → 模型 → `xy:<x>,<y>` 目标，置信度门限）；`LocatorService` 在 learned / snapshot / find / dom_hint 全部失败后才调用；适配器新增可选 `screenshot()`（Playwright 已实现、chrome-use 透传、Fake 可脚本化），Playwright 支持点击坐标目标；运行事件 `vision_fallback` 记录每次尝试。未注入 Provider 时行为与之前完全一致

### 阶段 D 验证记录

| 项 | 结果 |
|----|------|
| `pytest` 全量 | 171 通过、1 跳过（Network 非分页） |
| `mypy --strict` | 通过 |
| 新增用例（Network 非分页） | 解析多种请求形态、发现端点忽略非允许主机、必填字段缺失不学习、提取与回退、无能力不调用 |
| 新增用例（分页 Network） | 按页只读新响应、翻页两页均走 Network、Network + DOM 混合页 |
| Playwright 集成测试 | 本地站点 + 无头 Chrome：快照表格/引用、翻页、网络捕获、下载、弹窗、填表；Runner 端到端两页 Network 采集；无学习映射时 DOM 表格回退（无 Playwright/Chrome 时自动跳过） |

## 阶段 E：智能化与运营

- ✅ 样例对齐 Teach：`runtime/sample_alignment.py`，`test` 动作携带 `sample_path` 时把上传样例（CSV / JSON）与试跑记录比对——列到字段的匹配（key / 名称 / 语义 / 别名 / 归一化）、取值形态（整数 / 小数 / 日期 / 文本…）与填充率、未覆盖列与无值字段，以中文问题清单输出；写入 `runs/<run_id>/sample_alignment.json`，控制台 Teach 向导自动带上样例并显示差异
- ✅ 异常摘要：`pipeline/analyze.py` 规则引擎（校验问题、空结果、可选字段大面积为空、附件失败、分页未完成、与上次完成运行的记录数波动）输出 findings / severity / 中文摘要到 `pipeline.json` 与 `report.md`；`AnalysisProvider` 钩子供 Host Agent 注入模型生成 `ai_summary`，模型失败不影响运行；校验失败的运行同样产出分析（`pipeline.json` + 错误 details）
- ✅ 邮件 / 企业微信分发：`pipeline/deliver.py` 新增 `email`（SMTP，凭据来自 `UNIVERSAL_BROWSER_SMTP_*` 环境变量，正文含分析摘要，附结果文件，大小预算）与 `wecom`（群机器人 markdown 摘要 + `upload_media` 上传结果文件），渠道参数放 `delivery.channels[].options`
- ⬜ 模板权限与多用户审计（仅在引入服务端时；当前每人本机形态不需要）

### 阶段 E 验证记录

| 项 | 结果 |
|----|------|
| Vision | 定位顺序（DOM 命中不调用视觉）、低置信度 / 空 Provider 保持 `E_ELEMENT_NOT_FOUND`、无截图能力跳过、Runner 端到端点击 `xy` 目标并记录事件 |
| 样例对齐 | 形态分类、多策略列匹配、覆盖率 / 形态差异 / 无值字段报告、`test` 动作附带报告并落盘 |
| 分析 | 无异常运行、可选字段稀疏 + 记录数骤降对比上次、校验失败 → error、AI Provider 摘要与失败隔离、禁用即跳过 |
| 分发 | 邮件（Fake SMTP：收件人、主题、正文、附件、登录）、未配置 SMTP 时报告不抛错、企业微信（本地机器人：markdown + 上传 + 文件消息、错误 key 失败） |

## 发布 0.3.0（main，#21 + #22）

| 项 | 结果 |
|----|------|
| 合并 | `cursor/phase-e-intelligence-delivery-f629` → `main`（含分页 Network、Playwright、Vision、Analyze、邮件/企微） |
| 版本 | `0.3.0`（`install.py` / `hub.manifest.json` / `pyproject.toml`） |
| Hub 制品 | `./scripts/build-skill-package.sh --full` → `dist/universal-browser-full-0.3.0.zip`（≤5MB） |
| `pytest` 全量 | 203 通过、1 跳过 |

## 阶段 F：易用性（用户三步：解压 → 双击 → 点运行）

- ✅ 引擎自动选择 `browser/auto_engine.py`（`--engine auto` 为默认）：沿用已装 chrome-use → Playwright 驱动本机 Chrome → 缺 `playwright` 包时静默 `pip install`（`UNIVERSAL_BROWSER_NO_AUTO_PIP=1` 关闭）→ 回退 chrome-use 引导
- ✅ 双击启动器 `open-console.bat` / `open-console.sh`（打包到技能根目录）：自动找 Python、缺失时引导下载、打开控制台
- ✅ 控制台首屏环境自检 `GET /api/setup`（中文清单：驱动 / Chrome / 登录状态）与 `POST /api/setup/repair` 一键修复（安装 Playwright、chrome-use → Playwright 切换）
- ✅ 控制台文案面向业务：运行任务 / 历史结果 / 新建模板 / 设置；「测试运行」「含未发布」收进高级选项；登录提示改为「在弹出的 Chrome 登录一次 → 我已登录，继续」
- ✅ `invoke.py` 低版本 Python 给中文提示；`docs/QUICKSTART.zh.md` 一页三步随包分发；README / SKILL.md / STANDALONE 同步

## 里程碑验收

| 里程碑 | 判定 |
|--------|------|
| M1 界面可用 | 界面完成一次运行并下载制品 |
| M2 闭环可用 | 2.0 模板生成 report.md 且本地投递成功 |
| M3 定时可用 | 任务计划触发 `invoke.py run` 成功 |
| M4 稳定采集 | 同一模板在改版后通过 Repair 恢复 |
