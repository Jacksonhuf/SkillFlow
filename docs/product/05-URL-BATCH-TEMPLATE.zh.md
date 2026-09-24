# 方案 B：URL 批量模板（详情型）— 详细设计

> 目标：模板创建只需 **一个示例 URL**；系统探测页面后让用户 **勾选字段 / 附件**、**标出 URL 里的变量**，即成模板。日常运行时给一批变量值（单号列表 / CSV 一列），系统按 URL 模式批量打开页面、采集字段、下载附件，合并成一次 Run 产物。

本文是对现有 Template 2.0 + Learned Profile + Runner 的 **兼容扩展**，不重写采集引擎。

---

## 1. 范围与边界

| 项 | 本方案 | 说明 |
|----|--------|------|
| 模板类型 | **`detail_batch`**（新增） | 现有列表型（一个入口多条记录）保持为 `list` |
| 输入 | 示例 URL + 勾选 + 变量 | 不再要求先上传样例 CSV，也不要求手写 JSON |
| 运行输入 | 驱动变量的 **多个值** | 粘贴多行、上传 CSV 选一列、Agent 传数组 |
| 采集来源 | Network JSON → DOM（label/value、表格、链接） | 沿用 `acquire/strategies.py` 回退链 |
| 附件 | 页面内下载链接 / 下载按钮 | 支持 per-record 命名、类型过滤 |
| 登录 | 复用本机 Chrome 会话；未登录暂停 → `resume` | 不变 |
| 不做 | 无登录态的公网爬取、绕过验证码、代发 API | 与现安全策略一致 |

**能力前提**：URL 打开后目标信息 **能出现在页面或其 XHR 响应里**；若需额外点击（如「展开附件」），在向导里允许**记录一次点击**作为 `workflow.hints`（高级，可选）。

---

## 2. 用户流程（3 步）

### 步骤 1 · 给一个 URL

用户粘贴示例地址，例如：

```text
https://portal.example.com/orders/ORD-2024-0917/detail?tab=files
```

系统动作：

1. 在 Chrome 打开（Playwright 独立 Profile）；未登录 → 提示「在 Chrome 登录一次 → 我已登录，继续」。
2. **URL 分析**：把路径段与 query 拆成 token，标出**看起来像业务标识**的片段（含数字/大写字母/日期、且在同站其它链接中变化），默认建议 1 个变量：
   - `ORD-2024-0917` → 建议变量 `order_no`（用户可改名）
   - `tab=files` → 常量
3. **页面探测**（`probe`）：
   - Network：抓已发生的 JSON 响应，找**单对象**或**含该 ID 的对象**，列出扁平化后的键（`data.order.amount` → 候选字段「amount」）
   - DOM：label/value 对（如「订单金额：¥1,200」）、表格、`<a download>` / 含 `.pdf/.xlsx` 的链接、下载按钮
   - 每个候选给 **名称、示例值、来源（network/dom）、置信度**

输出到步骤 2 的**候选清单**，用户不需要理解 JSON。

### 步骤 2 · 选字段、选附件

界面为**两列勾选表**：

| 勾选 | 名称（可改） | 示例值 | 来源 | 类型（自动） |
|------|--------------|--------|------|--------------|
| ☑ | 订单号 | ORD-2024-0917 | URL 变量 | string（主键） |
| ☑ | 客户名称 | 张三贸易 | dom · label | string |
| ☑ | 金额 | 1200.00 | network | number |
| ☐ | 更新时间 | 2024-09-17 10:21 | dom | date |

附件区：

| 勾选 | 附件名 | 数量 | 类型 | 命名 |
|------|--------|------|------|------|
| ☑ | 合同 | 1 | pdf | `{order_no}_合同.pdf` |
| ☑ | 发票 | 多 | pdf/jpg | `{order_no}_发票_{n}.{ext}` |

规则：

- **主键**默认 = URL 变量（`order_no`），可改为页面某字段。
- 每个勾选字段自动生成 `key`（拼音/英文/清洗后的键名）+ 中文 `name` + `semantic`（用页面 label 与 JSON 键）。
- 附件默认 `per_record: true`、`match_by: [主键]`。

### 步骤 3 · 变量与批量方式，试跑，发布

- **URL 模板** 展示为 `https://portal.example.com/orders/{order_no}/detail?tab=files`，可手改。
- **批量输入方式**（运行时可选，模板只声明变量）：
  1. 文本框多行粘贴
  2. 上传 CSV / Excel，选一列
  3. Agent / CLI 传数组
- **试跑**：默认用示例 URL 的值跑 **1 条**；可再「试跑 3 条」（用户多贴 2 个值）。
- 试跑通过 → **发布**（沿用 `publish` 需 `run_id` 的规则）。

高级折叠项：额外「点一下再采集」步骤、每条等待时间、并发数、失败策略、去重。

---

## 3. 模板 Schema 扩展（兼容 2.0）

新增字段均为 **可选**，旧模板默认值等价于现在行为。

```yaml
schema_version: "2.0"
template_id: order_detail_pack
name: 订单详情资料包
status: published
version: 1

system:
  entry_url: https://portal.example.com/            # 登录检查用
  allowed_hosts: [portal.example.com]
  # 新增
  url_template: "https://portal.example.com/orders/{order_no}/detail?tab=files"

# 新增：运行模式
run:
  mode: detail_batch           # list | detail_batch（默认 list）
  driver_variable: order_no    # 每个值渲染一次 url_template
  concurrency: 1               # 同一 Chrome 会话建议 1；多标签可 2~3
  per_item_delay_ms: 300
  on_item_error: continue      # continue | stop
  dedupe_values: true
  max_items: 500
  accept_full_urls: true       # 驱动值为完整 URL 时直接打开（host 必须在 allowed_hosts）
  capture_tables: false        # 把详情页表格原样存为 tables/<主键>.json

variables:
  order_no:
    type: string
    required: true
    multiple: true              # 新增：允许多值（列表/CSV）
    prompt: 订单号（可多行或上传一列）
    validation: { regex: "^ORD-\\d{4}-\\d{4}$" }

target:
  record_key: [order_no]
  fields:
    - { key: order_no,      name: 订单号,   type: string, required: true,  semantic: [订单号], source: detail }
    - { key: customer_name, name: 客户名称, type: string, required: true,  semantic: [客户名称, customerName], source: detail }
    - { key: amount,        name: 金额,     type: number, required: false, semantic: [金额, amount], source: detail }
  attachments:
    - key: contract
      name: 合同
      required: true
      semantic: [合同, contract]
      source: detail
      per_record: true
      match_by: [order_no]
      file_types: [pdf]
      filename_pattern: "{order_no}_合同.{ext}"
    - key: invoice
      name: 发票
      required: false
      multiple: true
      semantic: [发票, invoice]
      source: detail
      match_by: [order_no]
      filename_pattern: "{order_no}_发票_{index}.{ext}"

workflow:
  hints: []                      # 可选：如 [{action: query, target: 附件}] 展开附件区

validation:
  min_records: 1
output:
  format: both
  filename_pattern: "orders_{run_date}"
```

模型变更点（`models.py`）：

| 位置 | 变更 |
|------|------|
| `SystemSpec` | `url_template: str | None`；校验占位符均为已声明变量、host 在 `allowed_hosts` |
| 新 `RunSpec` | `mode`、`driver_variable`、`concurrency`、`per_item_delay_ms`、`on_item_error`、`dedupe_values`、`max_items`、`accept_full_urls`、`capture_tables` |
| `VariableSpec` | `multiple: bool = False` |
| `AttachmentSpec.filename_pattern` | 新占位符 `{index}`、`{ext}`（已有 `{original_name}`） |
| `BrowserTemplate` | 校验：`mode == detail_batch` 时必须有 `url_template` 与 `driver_variable`，且 `driver_variable.multiple == true` |

Learned Profile 侧新增（`learned/{version}.yaml`）：

```yaml
learned:
  probe_url_sample: "https://portal.example.com/orders/ORD-2024-0917/detail?tab=files"
  field_mappings:
    customer_name: { page: detail, strategy: label_value, hints: [客户名称], preferred_source: dom }
    amount: { page: detail, strategy: semantic, hints: [amount], preferred_source: network,
              endpoint_hint: /api/orders/{order_no}, json_path: "$.data.amount" }
  attachment_mappings:
    contract: { page: detail, strategy: semantic, hints: [合同, 下载], preferred_source: dom }
```

`endpoint_hint` 允许含 `{driver_variable}` 占位，Run 时用当前值匹配已捕获响应。

---

## 4. 运行期设计（Runner 扩展）

### 4.1 执行流程

```text
run(template, variables={order_no: [v1, v2, ...]})
  ├─ 解析驱动值：去重 / 校验 regex / 截断 max_items
  ├─ AUTH_CHECK：open(entry_url) → 未登录 → WAIT_USER_AUTH（resume 后从第一个未完成项继续）
  ├─ for each value (按 concurrency 分批):
  │     url = value if (accept_full_urls and is_http_url(value)) else render(url_template, {order_no: value})
  │     policy.require_url_allowed(url)          # 渲染后 / 直传 URL 均校验 host 白名单
  │     open(url) → snapshot
  │     [可选 workflow.hints]
  │     record = extract_detail(fields)          # Network 优先 → DOM label/value
  │     files  = download_attachments(record)    # 命名 {order_no}_...
  │     item_status: ok | partial | failed(+reason)
  │     写 runs/<run_id>/batch.json（逐项断点）
  ├─ 合并 records → Process → Validate → Output(result.xlsx, attachments/, manifest.json)
  └─ summary.items: {total, ok, partial, failed, failed_values[]}
```

### 4.2 状态与断点续跑

- 新增 RunState 细分事件（不改枚举）：`item_started` / `item_finished` / `item_failed`。
- `runs/<run_id>/batch.json` 记录每个值的状态；`resume(run_id)` 跳过 `ok` 项。
- `on_item_error: continue` 时最终状态 `PARTIAL`，`summary.json` 给出 `failed_values`，控制台一键「只重跑失败项」。

### 4.3 提取（`extract_detail`）

优先级与现有 `acquire/strategies.py` 一致：

1. **Network**：在本次导航后捕获的 JSON 中，按 `endpoint_hint`（含占位符渲染）+ `json_path` 取值；
2. **DOM label/value**：`LearnedMapping.strategy=label_value`，用 `semantic` 找标签，取相邻值；
3. **表格**：详情页含表格时用 `table_header`；
4. **Vision**：保留兜底接口。

单条页面 = 单条记录；若详情页本身有**子表**（如多行发票），第一版仅支持 **附件多文件**，子表字段列为 P3。

### 4.4 附件

- 候选链接：`<a href>` 以 `.pdf/.xlsx/...` 结尾、`download` 属性、按钮文本含「下载 / 附件 / 合同」等 `semantic`。
- 命名：`filename_pattern` 支持 `{order_no}`（任意字段）、`{original_name}`、`{index}`、`{ext}`。
- 多附件 `multiple: true` 时按出现顺序编号；`max_count` 限制。
- 已存在同名文件按内容 hash 去重。

---

## 5. 探测（Probe）API 与算法

### 5.1 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/jobs` `{action: probe_url, url}` | 后台任务：打开 URL，返回候选字段 / 附件 / URL 变量建议 |
| POST | `/api/action` `{action: create_from_probe, probe_draft}` | 由勾选结果编译模板草稿 + Learned（`ProbeDraftInput`：`template_id/name/sample_url/url_template/driver_variable/fields/attachments/record_key/required_keys/run`） |
| POST | `/api/jobs` `{action: test, template_id, variables:{order_no:[...]}}` | 试跑 N 条 |
| POST | `/api/action` `{action: publish, ...}` | 不变 |

`probe_url` 返回：

```json
{
  "url_analysis": {
    "template_suggestion": "https://portal.example.com/orders/{order_no}/detail?tab=files",
    "variables": [{"name": "order_no", "sample": "ORD-2024-0917", "confidence": 0.86}]
  },
  "fields": [
    {"key": "customer_name", "name": "客户名称", "sample": "张三贸易", "source": "dom", "strategy": "label_value", "type": "string", "confidence": 0.9},
    {"key": "amount", "name": "金额", "sample": "1200.00", "source": "network", "endpoint_hint": "/api/orders/ORD-2024-0917", "json_path": "$.data.amount", "type": "number", "confidence": 0.95}
  ],
  "attachments": [
    {"key": "contract", "name": "合同", "count": 1, "types": ["pdf"], "sample_href": "/files/abc.pdf", "confidence": 0.8}
  ],
  "auth_state": "authenticated",
  "warnings": ["页面存在「展开更多」按钮，可能隐藏更多字段"]
}
```

### 5.2 URL 变量识别

对路径段与 query 值打分：

- 含数字、`-`/`_` 分隔的大写字母数字（`ORD-2024-0917`、`SN12345`）：+0.5
- 该值**出现在页面正文**中：+0.3（说明是业务主键）
- 在页面其它同站链接中同位置出现**不同值**：+0.2
- 纯英文单词（`orders`、`detail`）、常见 query 名（`tab`、`lang`）：-0.6

置信度 ≥0.6 的默认勾选为变量；用户可增删。

### 5.3 字段候选合并

- Network 键与 DOM label **同值**时合并为一个候选（来源标记 network，保留 dom 作回退）。
- 过滤：值为空、与主键重复、明显噱头（导航文本、按钮文字）。
- 类型推断复用 `SampleAnalyzer` 的规则（整数/小数/日期/文本）。

---

## 6. 控制台 UI（新建模板页重做）

```text
┌ 新建模板 ────────────────────────────────────────────────────┐
│ ① 粘贴一个页面地址  [ https://portal.example.com/orders/ORD-… ] [开始分析] │
│   状态：正在打开… / 请在 Chrome 登录后点「我已登录，继续」            │
├─────────────────────────────────────────────────────────────┤
│ ② 这个页面上你要哪些信息？                                      │
│   URL 中的变量： [order_no ▾]  = ORD-2024-0917   （改名 / 取消勾选）   │
│   字段（勾选）  ☑ 客户名称  ☑ 金额  ☐ 更新时间 …                     │
│   附件（勾选）  ☑ 合同(pdf×1)  ☑ 发票(pdf/jpg×多)                   │
│   记录主键： order_no ▾                                           │
├─────────────────────────────────────────────────────────────┤
│ ③ 命名并试跑                                                    │
│   模板名称 [订单详情资料包]  模板 ID [order_detail_pack]              │
│   试跑用的订单号（每行一个，默认示例）                                │
│   [ORD-2024-0917]                                                │
│   [试跑]  → 结果：1 条记录 · 2 个附件 · 校验通过                        │
│   [发布]                                                          │
│ ▸ 高级选项：额外点击步骤 / 并发 / 失败策略 / 去重                        │
└─────────────────────────────────────────────────────────────┘
```

「运行任务」页对 `detail_batch` 模板的变量输入改为：**多行文本 + 上传 CSV 选列**（自动去重、显示条数），运行中显示 **进度条 (12/100) 与失败清单**，结束后可「只重跑失败项」。

旧的五步 Teach（样例 → 草稿 → 发现 → 测试 → 发布）保留为 **「专家模式」** 折叠入口，服务列表型与复杂场景。

---

## 7. Agent / CLI 契约

```bat
py scripts\invoke.py run order_detail_pack --var order_no=ORD-1 --var order_no=ORD-2
py scripts\invoke.py run order_detail_pack --var-file orders.csv --var-column order_no
py scripts\invoke.py probe https://portal.example.com/orders/ORD-2024-0917/detail
```

- `--var` 重复同名 → 聚合为数组（`multiple: true` 变量）。
- `--var-file` + `--var-column`：从 txt / CSV / TSV / XLSX 读一列（表格首行为表头，列名或 1 起序号，默认第 1 列；`--var-name` 指定非驱动变量）。与 `--var` 同时给出时合并。
- Agent 执行契约（`references/agent-execution.zh.md`）新增：对 `detail_batch` 模板，Agent 收集**一组值**而不是单值；返回 `data.items` 进度与 `failed_values`。

---

## 8. 性能与稳定性优化

| 优化 | 做法 | 收益 |
|------|------|------|
| **Network 优先** | 探测时若接口 JSON 覆盖所勾字段，运行时直接读响应，不解析 DOM | 更快、抗改版 |
| **并发多标签** | `concurrency` 2~3 时用 Playwright 多 page 同 context | 单机吞吐提升 2~3 倍；默认 1 保证稳定 |
| **限速与抖动** | `per_item_delay_ms` + 随机 ±30% | 降低被风控概率 |
| **断点续跑** | `batch.json` 每项状态；`resume` 只跑未完成 | 中途登录过期/断网不重来 |
| **增量运行** | 可选 `skip_if_exists`：同主键上次 `ok` 且附件已在则跳过 | 每日补数只跑新增 |
| **附件去重** | 内容 hash + 大小阈值 | 避免重复下载 |
| **失败分类** | `auth_required` / `not_found(404)` / `no_data` / `download_failed` | 控制台按类聚合，方便一键重跑 |
| **URL 白名单** | `url_template` host 必须 ∈ `allowed_hosts`；渲染后再校验 | 防止变量注入跳到外站 |
| **值校验前置** | 驱动变量 `regex`，不合法项直接进 failed 不打开页面 | 省时间、少误报 |

---

## 9. 安全与合规

- 仅本机 Chrome 会话，不存密码/Cookie；沿用脱敏持久化。
- `url_template` 渲染值做 URL 编码；禁止 `javascript:`、`file:`；仅 `http(s)`。
- 附件落盘限定 `runs/<run_id>/attachments/`；文件名 `safe_filename`。
- Network 仅读取**浏览器已发生的响应**，不主动构造请求（与现架构一致）。

---

## 10. 测试计划（增量）

| 层 | 用例 |
|----|------|
| 单元 | URL 变量识别评分；`url_template` 渲染与 host 校验；`multiple` 变量解析（多行/CSV/数组）；`filename_pattern` 新占位符 |
| 组件 | Fake 适配器：3 个值 → 3 条记录 + 附件命名；中途 1 个 404 → `PARTIAL` + `failed_values`；`resume` 跳过已完成 |
| 组件 | probe：给定 DOM/Network 快照 → 候选字段/附件与置信度 |
| 控制台 | `/api/jobs probe_url`、`create_from_probe` 生成合法模板并可 `test`；进度与失败清单展示 |
| 回归 | 旧 `list` 模板行为不变（默认 `run.mode: list`） |

---

## 11. 实施拆解（PR 粒度）

| 阶段 | 内容 | 主要文件 |
|------|------|----------|
| **P1 · Schema + 渲染**（已完成） | `RunSpec`、`url_template`、`multiple`、渲染与校验、旧模板兼容测试 | `models.py`, `interaction/variables.py`, `runtime/policy.py` |
| **P2 · Runner 批量**（已完成） | `detail_batch` 循环、`batch.json`、续跑、失败汇总、多附件命名；并发暂为串行 | `runtime/runner.py`, `runtime/batch.py`, `outputs/writer.py` |
| **P3 · Probe**（已完成） | `probe_url` 动作：URL 分析 + DOM/Network 候选 + 置信度；`create_from_probe` 编译草稿；运行期新增文本 label/value 与详情页 JSON 取值 | `runtime/url_probe.py`, `runtime/probe_compiler.py`, `acquire/label_value.py`, `app.py` |
| **P4 · 向导 UI**（已完成） | 新建模板 3 步页（探测 → 勾选 → 命名/试跑/发布）、运行页多值输入（多行 / 文件导入选列）、逐项进度、失败项一键重跑、历史页批量明细；旧样本流程折叠 | `console/ui.html`, `console/server.py`, `runtime/runner.py`（`progress_listener`） |
| **P5 · CLI/Agent**（已完成） | `--var` 重复聚合为数组；`--var-file/--var-column/--var-name`（txt / CSV / TSV / XLSX 读一列，请求字段 `values_file/values_column/values_variable`）；`probe` 子命令；`run`/`test` 输出批量统计；执行契约文档新增批量与 probe 章节 | `skill-scripts/invoke.py`, `cli.py`, `interaction/value_files.py`, `references/agent-execution.zh.md`, `SKILL.md` |
| **P6 · 优化** | 并发多标签、增量、附件去重、失败一键重跑 | Runner / UI |

各阶段可独立合并；P1–P2 先落地即可用 CLI 批量跑，P3–P4 提供业务用户体验。

---

## 12. 风险与对策

| 风险 | 对策 |
|------|------|
| 页面数据需点击后才出现 | 向导「高级」允许录一次点击为 `workflow.hints`；probe 提示「检测到展开按钮」 |
| ID 在 URL 中不显式（如内部数字 id） | **已定（P1）**：驱动值可直接是完整 `http(s)` URL（host ∈ `allowed_hosts`），此时跳过 `url_template` 渲染；用户从列表页复制链接或导出一列 URL 即可。「列表页搜索 → 详情」作为后续增强 |
| 站点风控 | 默认并发 1、延迟、随机抖动；失败可续跑 |
| 详情页含子表 | **已定**：第一版仅多附件；可选 `run.capture_tables: true` 把详情页表格原样存到 `runs/<run_id>/tables/<主键>.json`，后续 `sub_records` 直接升级 |
| 登录过期于中途 | 项级 `auth_required` → 整体 `WAIT_USER_AUTH`，`resume` 继续 |

---

## 13. 与现有文档关系

- 补充 `01-PRD.zh.md` §4.2「首次创建」：增加 **URL 探测式创建** 为默认路径，样例式为专家路径。
- `02-SOLUTION.zh.md` §3.2 API 表新增 `probe_url` / `create_from_probe`。
- `references/template-schema.md` 记录 `run` / `url_template` / `multiple` / 新占位符。
