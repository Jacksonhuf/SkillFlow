# 独立模式：Windows + OpenCode Agent + chrome-use（无其它平台）

适用：**Windows 10/11**，Skill Hub / OpenCode 技能 + Chrome 里的 **chrome-use 扩展**。

## Skill Hub 上传哪个包（≤5MB）

**只上传完整技能包（不含 chrome-use.exe）：**

https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.1.5-full/universal-browser-full-0.1.5.zip

约 **1MB 以内**：`SKILL.md`、`references/`、`templates/`、`runtime/`、`scripts/`。

**不要**上传带 `vendor/chrome-use/chrome-use.exe` 的包（约 20MB，超过 Hub 限制）。

## chrome-use CLI 放哪（不进 Skill zip）

| 方式 | 说明 |
|------|------|
| **推荐：机器级一次安装** | 首次 `invoke.py run` 自动从 GitHub 下载到 `.universal-browser\chrome-use\`（需能访问 github.com） |
| **内网** | 设置 `CHROME_USE_BIN` 或 `CHROME_USE_WINDOWS_DOWNLOAD_URL` / `CHROME_USE_LOCAL_ARCHIVE` |
| **Sidecar 包（IT 分发，非 Hub）** | `universal-browser-chrome-use-sidecar-*.zip` 解压到技能目录，得到 `vendor\chrome-use\chrome-use.exe` |

完整包 **内置 Python 运行时**，**不内置** chrome-use 二进制（与 Chrome 扩展分开）。

## 用户要做什么

1. 在 Chrome 安装并启用 [chrome-use 扩展](https://chromewebstore.google.com/detail/chrome-use/knfcmbamhjmaonkfnjhldjedeobeafmk)，保持登录。  
2. 在 Agent 里使用本技能，按业务选模板、填变量。

CLI 由运维/首次运行准备，**不要**在对话里让用户安装 CLI。

## Agent 后台命令

```bat
py scripts\invoke.py start
py scripts\invoke.py run <template_id> --var name=value
py scripts\invoke.py resume <run_id>
```

## 运维

| 场景 | 处理 |
|------|------|
| Hub 5MB 限制 | 只用 **full** zip，不用 sidecar 当 Skill 上传 |
| Sidecar 解压 | 将 `chrome-use-sidecar-*.zip` 解压进 `universal-browser\`（覆盖/合并 `vendor\`） |
| **一键安装器（推荐 IT）** | 解压 `chrome-use-installer-*.zip`，双击 `install-chrome-use-stack.bat`（CLI+桥接+打开扩展商店） |
| 关闭自动下载 | `set UNIVERSAL_BROWSER_SKIP_CHROME_USE_INSTALL=1` |
| 指定 CLI | `set CHROME_USE_BIN=...` |

官方文档：https://chrome-use.leeguoo.com/en/install.html
