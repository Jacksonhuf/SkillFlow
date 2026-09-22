# 测试方案 — 模板驱动的业务数据自动化平台

## 1. 测试分层

| 层级 | 目标 | 手段 | 目录 |
|------|------|------|------|
| 单元 | 模型校验、存储、管线阶段、控制台 API | pytest + FakeBrowserAdapter | `tests/unit/` |
| 组件 | Runner 全链路、Teach/Repair、恢复 | pytest + 脚本化 Fake 适配器 | `tests/component/` |
| 集成 | 真实 chrome-use + 扩展（内网授权环境） | `pytest -m integration` | `tests/integration/` |
| 打包 | 完整包 ≤5MB、结构完整 | `tests/unit/test_install.py` | — |
| 手工验收 | 界面 + 真实模板 | 验收清单 | 本文 §4 |

## 2. 自动化用例矩阵

### 2.1 模板与 Learned Profile

| ID | 用例 | 预期 |
|----|------|------|
| T-01 | 1.0 模板加载 | 与既有行为一致 |
| T-02 | 2.0 模板保存 | learned 写入 `learned/{v}.yaml`，主 YAML 不含 learned 正文 |
| T-03 | 加载 2.0 模板 | 自动合并 learned |
| T-04 | `match_by` 引用未知字段 | 校验失败 |
| T-05 | Repair 候选 | 业务契约（含 processing/report/delivery）不变 |

### 2.2 管线阶段

| ID | 用例 | 预期 |
|----|------|------|
| P-01 | processing rename/dedupe/coerce/default | 记录按步骤变换 |
| P-02 | processing disabled | 透传 |
| P-03 | report enabled | 生成 `report.md`，含标题与记录数 |
| P-04 | delivery local | 制品复制到目标目录 |
| P-05 | delivery webhook | 发送 JSON（测试用本地 HTTP 服务接收） |
| P-06 | delivery webhook 失败 | 运行仍成功，pipeline.json 记录错误 |
| P-07 | manifest | 每条记录 bundle 与附件关联 |

### 2.3 控制台

| ID | 用例 | 预期 |
|----|------|------|
| U-01 | 无令牌访问 `/api/*` | 401 |
| U-02 | `/api/templates` | 返回已发布模板 |
| U-03 | `POST /api/jobs run` | 返回 job_id；轮询至完成，含 run_id |
| U-04 | `/api/runs/{id}` | summary / manifest / pipeline |
| U-05 | 下载制品路径越界 | 404 / 拒绝 |
| U-06 | `/api/doctor` | 返回探测报告 |
| U-07 | `/api/action analyze_sample` | 复用 App 契约 |

### 2.4 采集规划

| ID | 用例 | 预期 |
|----|------|------|
| A-01 | preferred_source=network | 回退链首位为 network |
| A-02 | 无 learned | 默认 DOM 开头 |

## 3. 质量门

```bash
.venv/bin/pytest -q                 # 全部单元+组件
.venv/bin/ruff check src tests      # lint
.venv/bin/mypy                      # 类型（strict）
./scripts/build-skill-package.sh    # 包体 ≤5MB
```

## 4. 手工验收清单（本机 Windows）

1. 解压完整包，`py scripts\invoke.py doctor` 通过。
2. `py scripts\invoke.py ui` 自动打开浏览器，显示模板列表。
3. 选模板填变量运行；未登录时出现「请在 Chrome 登录」并可续跑。
4. 运行完成后可下载 `result.xlsx`、查看 `manifest.json`、`report.md`。
5. 配置 `delivery.local` 后，目标目录出现制品副本。
6. Teach 面板：上传样例 → 草稿 → 发现 → 测试 → 发布，模板出现在列表。
7. 注册定时任务脚本后，任务计划程序中可见并可手动触发。

## 5. 缺陷分级

- P0：数据错误、越权路径、凭证泄露。
- P1：运行失败无法恢复、界面不可用。
- P2：体验问题、文案。
