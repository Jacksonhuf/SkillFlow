# 独立模式：Windows + OpenCode Agent + chrome-use（无其它平台）

适用：**Windows 10/11**，Skill Hub / OpenCode 技能 + Chrome 里的 **chrome-use 扩展**。

## 用哪个包

https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.1.4-full/universal-browser-full-0.1.4.zip

解压得到 `universal-browser/`，上传到 Skill Hub。

# 完整包内含：SKILL、references、templates、runtime、scripts。**不含** chrome-use CLI 二进制（第三方、体积大）。

## chrome-use CLI 从哪来

| 方式 | 说明 |
|------|------|
| **默认** | 首次 `invoke.py start/run` 时从 **GitHub** 下载 win32 包到 `.universal-browser\chrome-use\`（需能访问 github.com） |
| **内网/防火墙** | 运维预置 `universal-browser\vendor\chrome-use\chrome-use.exe`，或设置 `CHROME_USE_BIN` / `CHROME_USE_LOCAL_ARCHIVE` / 镜像 URL `CHROME_USE_WINDOWS_DOWNLOAD_URL` |
| **自带 CLI 的完整包** | 打 zip 前在仓库执行 `./scripts/fetch-chrome-use-windows.sh`，再 `./scripts/build-skill-package.sh --full`（会把 `vendor/` 打进 zip） |

**常见误解：**「完整包已内置 Chrome CLI」—— 默认 **没有**；只有 Python 运行时。扩展仍在 Chrome 里安装；CLI 按上表准备。

## 用户要做什么

1. 在 Chrome 安装并启用 [chrome-use 扩展](https://chromewebstore.google.com/detail/chrome-use/knfcmbamhjmaonkfnjhldjedeobeafmk)，保持登录。  
2. 在 Agent 里使用本技能，按业务选模板、填变量。

**不需要**向用户说明或让用户安装 **chrome-use CLI**：首次执行技能时，Agent 在后台运行 `scripts\invoke.py`，Windows 会自动把 CLI 下载到 `.universal-browser\chrome-use\`（用户无感）。

**不需要**让用户运行 `doctor` 或配置 `CHROME_USE_BIN`。

需要用户配合的典型情况只有一种：任务提示 **请在 Chrome 登录** 时，用户在浏览器里登录，Agent 再 `resume`。

## Agent 后台命令（勿当作用户步骤）

```bat
py scripts\invoke.py start
py scripts\invoke.py run <template_id> --var name=value
py scripts\invoke.py resume <run_id>
```

`doctor` 仅供运维排查，不要作为对话里的用户指引。

## 运维（用户不可见）

| 场景 | 处理 |
|------|------|
| 关闭自动下载 CLI | `set UNIVERSAL_BROWSER_SKIP_CHROME_USE_INSTALL=1` |
| 指定 CLI 路径 | `set CHROME_USE_BIN=...` |
| 指定下载版本 | `set CHROME_USE_INSTALL_VERSION=v1.5.131` |
| GitHub 超时 / 内网 | 见上文 **vendor/** 或 `CHROME_USE_WINDOWS_DOWNLOAD_URL` / `CHROME_USE_LOCAL_ARCHIVE` |

官方文档：https://chrome-use.leeguoo.com/en/install.html
