# 独立模式：Windows + OpenCode Agent + chrome-use（无其它平台）

适用：**Windows 10/11**，只有 Skill Hub / OpenCode 技能 + 本机 **chrome-use 扩展与 CLI**，无自研 Agent 平台。

## 用哪个包

下载 **完整包**（不要下 slim 包）：

https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.1.0-full/universal-browser-full-0.1.0.zip

解压后得到 `universal-browser/`，上传到 Skill Hub 或放到 OpenCode 技能目录。

## 目录里有什么（除 chrome-use 外全在这里）

```text
universal-browser/
├── SKILL.md
├── references/
├── templates/
├── runtime/
├── scripts/
│   ├── invoke.py
│   ├── invoke.bat      # 双击或 cmd 里调用
│   └── setup.sh        # 非 Windows 开发用，可忽略
└── STANDALONE.zh.md
```

**唯一外部依赖**：Chrome 里的 [chrome-use 扩展](https://chromewebstore.google.com/detail/chrome-use/knfcmbamhjmaonkfnjhldjedeobeafmk) **和配套的 CLI**（只装扩展不够）。

## 首次自动安装 CLI（推荐）

在技能目录打开 **cmd** 或 **PowerShell**（需联网）：

```bat
py scripts\invoke.py doctor
```

或：

```bat
scripts\invoke.bat doctor
```

第一次若找不到 `chrome-use`，技能会从 GitHub Releases 下载官方 **`chrome-use-win32-x64.tar.gz`**，解压到：

```text
.universal-browser\chrome-use\chrome-use.exe
```

并尝试执行一次 `chrome-use extension install`（与已安装的扩展桥接）。每个技能副本只自动装 **一次**（标记 `.universal-browser\chrome-use-auto-install.done`）。

关闭自动安装：

```bat
set UNIVERSAL_BROWSER_SKIP_CHROME_USE_INSTALL=1
py scripts\invoke.py --no-auto-install-chrome-use doctor
```

指定其它 release 版本（可选）：

```bat
set CHROME_USE_INSTALL_VERSION=v1.5.131
```

## 手动安装 CLI

从 [chrome-use Releases](https://github.com/leeguooooo/chrome-use/releases) 下载 `chrome-use-win32-x64.tar.gz`，解压后：

```bat
set CHROME_USE_BIN=C:\path\to\chrome-use.exe
py scripts\invoke.py doctor
```

官方文档：https://chrome-use.leeguoo.com/en/install.html

## Agent 怎么执行（OpenCode）

1. 加载技能 `universal-browser`。  
2. 需要跑浏览器时，在技能目录执行：

```bat
py scripts\invoke.py doctor
py scripts\invoke.py templates
py scripts\invoke.py run inventory_feedback --var date=2026-09-20
py scripts\invoke.py resume <run_id>
```

输出为 JSON；Agent 读结果继续对话。

可选环境变量：

```bat
set UNIVERSAL_BROWSER_SKILL_ROOT=D:\path\to\universal-browser
```

## 用户只需

1. 安装 chrome-use 扩展并保持 Chrome 登录。  
2. 启用本技能；在 Windows 上首次运行 `py scripts\invoke.py doctor`（可自动下载 CLI）。

不需要：单独平台、SkillFlow git clone。
