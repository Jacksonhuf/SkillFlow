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

- ✅ Windows 任务计划脚本 `scripts/windows/Register-ScheduledRun.ps1`
- ✅ SKILL.md / references / STANDALONE 文档更新（`ui` 命令与本机界面说明）
- ✅ 完整包体积门禁保持 ≤5MB

## 阶段 D：稳定采集（后续 PR）

- ⬜ Teach 阶段监听 XHR，写入 `preferred_source: network` + `endpoint_hint`
- ⬜ Network 采集器（复用浏览器 Session 读取 JSON）
- ⬜ Playwright 适配器（`BrowserAdapter` 协议实现）
- ⬜ Vision 兜底接口

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
