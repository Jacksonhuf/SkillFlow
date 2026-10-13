# 升级到 Universal Browser 0.3.27

面向从 **0.3.22 及更早** 独立包或控制台用户。完整包下载见 [GitHub Releases v0.3.27](https://github.com/Jacksonhuf/SkillFlow/releases/tag/v0.3.27)。

## 1. 安装

1. 关闭正在运行的旧控制台（`open-console.bat` 黑窗口与 `127.0.0.1:8771` 标签页）。
2. 解压 `universal-browser-full-0.3.27.zip` 到新目录，或覆盖 `runtime/` 与 `scripts/`（保留本机 `templates/` 与 `runs/`）。
3. 双击 `open-console.bat` / `open-console.sh`，确认页眉版本为 **0.3.27**。

CLI 路径：`py scripts\invoke.py capabilities` 中 `meta.version` 应为 `0.3.27`。

## 2. 引擎

| 能力 | Playwright（推荐） | chrome-use |
|------|-------------------|--------------|
| 网络 JSON / 二进制附件 | 支持 | 基本仅点击下载 |
| iframe / PDF 预览附件 | 支持 | 不支持 |
| 录制「运行前点击」 | 支持 | 不支持 |
| 附件阶段网络窗口 | 支持 | 忽略（无抓包） |

运维可设 `UNIVERSAL_BROWSER_ENGINE=playwright`（默认 `auto` 已优先 Playwright）。

## 3. 模板是否要重做探测

**建议重新探测并发布**（尤其附件在折叠区、华为/财务 SPA）：

- `workflow.hints`（`phase: attachments`）来自向导「运行前点击」或录制。
- `learned.attachment_mappings` 来自网络探测；旧草稿可能缺少接口映射。
- `record_key` / 批量校验在 0.3.19+ 已收紧；旧模板若整单校验失败需核对主键字段。

仅升级运行时、模板未改：可先试跑 1 条；若附件 `missing` 或 `failure_detail` 为 `no_dom_target`，再探测。

## 4. 向导操作（附件在折叠区）

1. **探测页面** → 步骤 2 **运行前点击**：勾选推荐项，或 **开始录制** → 在 Chrome 点展开/附件 Tab → **结束录制**。
2. 高级里可设 **每个附件下载等待（毫秒）**（默认 45000）。
3. 试跑后看 **历史结果** 或 `run.json` 的 `attachment_failures`（含 `failure_detail` 阶梯）。

CLI 等价：`probe-record start <URL>` → 在 Chrome 操作 → `probe-record stop`。

## 5. 结果与 Excel

- 结果目录：运行完成 JSON 中的 `output_dir`（0.3.20+）。
- CSV：使用新生成的 `result.csv`（UTF-8 BOM，Excel 中文不乱码）。
- 运行中勿关闭自动化 Chrome（0.3.21+ 会提示重新打开）。

## 6. 已知限制（0.3.27）

- `run.concurrency` 大于 1 时**仍串行**执行批量项（**0.3.29+** Playwright 已支持多标签并行，见 `UPGRADE-0.3.29.zh.md`）。
- **跨域 iframe** 无法读 DOM；请用录制展开或网络附件映射。
- 站点定制仅含轻量 `site_profiles`（华为 / efinance 类提示），非完整插件体系。

## 7. 回滚

保留旧 zip 与 `runs/` 即可；模板 YAML 向前兼容。若需回退引擎行为，设 `UNIVERSAL_BROWSER_ENGINE=chrome-use`（附件能力会减弱）。
