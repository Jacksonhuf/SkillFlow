# 产品需求文档（PRD）— 模板驱动的业务数据自动化平台

版本：1.0　状态：已确认关键决策　适用仓库：SkillFlow（Universal Browser Skill）

## 1. 产品定位

把重复性的企业 Web 数据工作固化为 **可重复、可自动运行的业务模板**：

> 用户第一次只定义「我要什么结果」；系统学习如何从目标系统获取数据与附件并固化为模板；之后只需选模板、填少量变量，自动完成采集 → 标准化 → 处理 → 校验 → 分析 → 报告 → 分发。

原则：**简单留给用户，复杂留给系统。** 业务用户不接触 DOM / XPath / Selector / API / Playwright 等概念。

## 2. 已确认的产品决策

| 决策项 | 结论 | 影响 |
|--------|------|------|
| 主入口 | **Agent + Skill 为主入口，同时提供本地界面** | 运行时以 Skill 包分发；界面为本机轻量控制台，不依赖服务端 |
| Session 归属 | **每人本机 Chrome，不做集中 Runner** | 复用用户已登录 Chrome Profile；无共享账号池、无集中调度节点 |
| 分发 | Skill Hub ≤5MB；chrome-use CLI 机器级/内网制品 | 界面与管线必须零重依赖（Python 标准库 + 现有依赖） |
| 认证 | 不自动化登录；未登录时暂停等待人工认证后自动续跑 | 模板不存明文凭证 |

## 3. 用户与场景

| 角色 | 目标 | 入口 |
|------|------|------|
| 业务用户 | 选模板、填变量、拿结果包与报告 | Agent 对话 / 本地界面 |
| 模板管理员 | Teach 新模板、测试、发布、站点改版后 Repair | 本地界面（Teach 面板）/ Agent |
| 运维 / IT | 分发 Skill、CLI、扩展；诊断环境 | 界面「环境诊断」/ `invoke.py doctor` |

典型模板：销售日报、样机盘点反馈、供应商订单资料包、财务对账数据、合同附件下载。

## 4. 功能需求

### 4.1 模板（核心对象）

- FR-T1 模板包含 Source / Variables / Targets / Attachments / Processing / Validation / Analysis / Report / Delivery。
- FR-T2 字段支持 name、type、required、aliases、source hint、validation rule。
- FR-T3 附件为一等公民：类型、必需、单/多、命名规则、关联键（match_by）、大小校验、去重、完整性。
- FR-T4 **Template（要什么）与 Learned Profile（怎么拿）分离**；改版只重学 Profile，模板契约不变。
- FR-T5 模板版本不可变；仅测试通过并经用户确认的版本可发布。

### 4.2 首次创建（Teach / Discovery）

- FR-D1 输入：目标 URL、结果样例（Excel/CSV/JSON）、变量标注、字段/附件需求、后处理与输出要求。
- FR-D2 系统在已登录 Chrome 中探索页面、建立字段映射、试跑、校验，生成草稿模板。
- FR-D3 用户确认「这就是我要的结果」后发布。

### 4.3 日常执行

- FR-R1 选择模板后只询问模板定义的变量；支持默认值（如 `yesterday`）。
- FR-R2 执行流程：登录检查 → 导航 → 采集 → 附件 → 标准化 → 处理 → 校验 → 输出 → 分析 → 报告 → 分发。
- FR-R3 未登录时暂停并提示人工认证；认证后 `resume` 继续。
- FR-R4 触发方式：Agent / 界面手动 / 本机定时任务 / 命令行；预留 API、Webhook 触发。

### 4.4 采集引擎

- FR-A1 采集策略优先级：API → Network/XHR → DOM → Browser UI → Vision；由 Learned Profile 的 `preferred_source` 决定并可回退。
- FR-A2 当前实现以 chrome-use（DOM / 浏览器工作流）为主；Network / Playwright / Vision 为规划接口。

### 4.5 输出与闭环

- FR-O1 每次运行产出 `result.(xlsx|csv|json)`、`manifest.json`、`summary.json`、`pipeline.json`、附件目录。
- FR-O2 Processing：重命名、类型转换、默认值、去重。
- FR-O3 Report：生成 Markdown 报告（标题、概览、校验、样例记录、附件统计）。
- FR-O4 Delivery：本地目录投递、Webhook 通知（JSON 摘要）；邮件等为占位。
- FR-O5 Analysis：AI 分析为可插拔占位，记录输入上下文，不在 Skill 内直接调用模型。

### 4.6 本地界面（控制台）

- FR-U1 仅绑定 `127.0.0.1`，带会话令牌；随 Skill 包分发，零额外依赖。
- FR-U2 模板列表与变量表单，一键运行；显示执行状态与结果制品下载。
- FR-U3 运行历史：状态、记录数、附件数、校验结果、错误信息。
- FR-U4 环境诊断：CLI / 扩展 / 能力探测。
- FR-U5 Teach 面板：样例分析、创建草稿、发现映射、测试、发布（结构化表单 + 高级 JSON）。
- FR-U6 认证暂停时提示「在 Chrome 完成登录」并提供一键续跑。

## 5. 非功能需求

- NFR-1 Skill 包 ≤5MB；运行时仅依赖 pydantic + PyYAML。
- NFR-2 模板与运行记录不含明文凭证；敏感变量脱敏。
- NFR-3 全部路径受控（禁止越出 runs/、templates/）。
- NFR-4 单机、多模板并发运行通过运行目录隔离；界面同一时刻一个浏览器任务（Chrome 单会话约束）。
- NFR-5 可在内网无 GitHub 情况下完成分发（沿用 sidecar / 安装器 / 镜像变量）。

## 6. 范围外（本阶段）

- 集中 Runner、共享账号池、多租户权限。
- 自动化登录 / 绕过 MFA。
- 对目标系统执行提交、审批、付款等写操作。
- 在 Skill 内直接调用大模型（由 Host Agent 负责）。

## 7. 验收标准（摘要）

1. 业务用户在界面或 Agent 中 3 步内完成一次运行并得到 `result` + `manifest`。
2. 未登录场景可暂停并在认证后续跑成功。
3. 站点改版后 Repair 只改 Learned Profile，模板 YAML 契约字段不变。
4. 界面所有 API 受令牌保护，仅本机可访问。
5. 全量单元/组件测试通过；打包体积 ≤5MB。
