# 模板驱动的业务数据自动化平台 — 架构说明

SkillFlow（Universal Browser Skill）正在从「浏览器任务技能包」演进为 **以 Template 为核心的业务数据自动化运行时**。Host 平台仍负责对话、身份与 UI；本仓库提供 **模板、采集、校验、输出与可扩展的后处理管线**。

## 产品闭环

```text
定义目标 → 自动采集 → 下载附件 → 数据标准化 → 业务处理 → 校验 → AI 分析 → 报告 → 分发
Acquire   → Normalize  → (attachments) → Process      → Validate → Analyze → Report → Deliver
```

当前实现状态：

| 阶段 | 模块 | 状态 |
|------|------|------|
| Acquire | `runtime/runner.py` + chrome-use 适配器 | 已实现（DOM/浏览器/UI） |
| Normalize | `runtime/extractor.py`, `table_parser.py` | 已实现 |
| Process | `pipeline/process.py` | 扩展点（默认透传） |
| Validate | `runtime/validator.py` | 已实现 |
| Analyze | `pipeline/analyze.py` | 扩展点（占位） |
| Report | `outputs/writer.py`, `outputs/manifest.py` | 表格输出 + manifest |
| Deliver | `pipeline/deliver.py` | 扩展点（占位） |

采集策略优先级（`acquire/strategies.py`）：

```text
API → Network/XHR → DOM → Browser workflow → Vision
```

Network/API/Vision 适配器为 **规划接口**；Teach/Discovery 会写入 `preferred_source` 到 Learned Profile，供后续引擎选用。

## 核心对象

### Template（业务契约 — 「我要什么」）

YAML `schema_version: "2.0"` 在 1.0 基础上增加：

- `processing` — 标准化/清洗规则（占位）
- `analysis` — AI 分析配置（占位）
- `report` — 报告生成（占位）
- `delivery` — 分发渠道（占位）
- 字段/附件支持 `aliases`、`match_by`、`multiple` 等

`system` / `variables` / `target` / `validation` / `output` 与 1.0 兼容。

### Learned Profile（站点实现 — 「上次怎么拿到的」）

与模板版本 **分文件存储**：

```text
templates/<template_id>/
├── metadata.json
├── 1.yaml          # 业务契约（2.0 不含 learned 正文）
└── learned/
    └── 1.yaml      # LearnedSpec + preferred_source 等
```

网站改版时：**Template 不变**，重新 Teach/Repair 仅更新 Learned Profile。

### Run 产物

```text
runs/<run_id>/
├── result.xlsx | result.json | result.csv
├── manifest.json       # 业务包清单（记录 + 附件布局）
├── attachments/...
└── summary.json
```

## 使用方式（不变）

Agent / CLI 仍通过 `invoke.py` 的 `start` → `run` / `test` → `publish` 流程；执行契约见 `references/agent-execution.zh.md`。

## 后续路线图

1. Playwright 适配器与 Network 监听器接入 `acquire/`
2. Teach 模式自动推断 XHR endpoint → `preferred_source: network`
3. `processing` / `analysis` / `delivery` 插件注册表
4. 定时任务 / Webhook / HTTP API 由 Host 平台或 sidecar 服务触发同一 `BusinessPipeline`
