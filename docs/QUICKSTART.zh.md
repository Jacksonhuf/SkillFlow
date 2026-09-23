# 快速开始（3 步）

不需要懂浏览器插件、命令行或任何配置。

## 1. 解压

把 `universal-browser-full-*.zip` 解压到任意目录，例如 `D:\universal-browser\`。

需要电脑上装有 **Google Chrome** 和 **Python 3.11+**（推荐 3.12；没有 Python 时启动器会带你去下载页，安装时勾选 *Add python.exe to PATH*）。

## 2. 双击打开

| 系统 | 双击 |
|------|------|
| Windows | `open-console.bat` |
| macOS / Linux | `open-console.sh` |

会自动弹出一个网页（只在你本机 `127.0.0.1` 可访问，**无需 token**）。第一次打开时系统自动准备浏览器驱动，页面顶部会显示「环境就绪」；如果缺什么，会给出 **「一键修复」** 按钮，点它即可。

## 3. 点任务，填信息，开始运行

1. 在「运行任务」里点一个任务卡片。
2. 填上它要求的信息（比如日期）。
3. 点 **开始运行**。

第一次运行会弹出一个 Chrome 窗口：**在里面登录目标系统一次**，回到网页点 **「我已登录，继续」**。之后系统自动复用登录状态，不再打扰你。

运行结束后在「历史结果」下载 **结果文件**、**报告**，或按任务配置自动发到指定目录 / 邮件 / 企业微信。

---

## 常见问题

| 现象 | 处理 |
|------|------|
| 双击后提示没有 Python / 版本过低 | 安装 [Python 3.12](https://www.python.org/downloads/)（勾选 PATH）；若已装 3.12 仍报错，用 `py -3.12 scripts\invoke.py ui` 或更新到 0.3.2+ 启动器 |
| 页面仍像旧版（要 token / 没有版本号） | 关掉所有旧黑色窗口和 `127.0.0.1` 标签页；双击新版本 `open-console.bat`（0.3.8+ 会自动关闭本机旧控制台并占用 8765） |
| 顶部提示「未找到 Google Chrome」 | 安装 Chrome 后点「重新检测」 |
| 顶部提示「浏览器驱动尚未安装」 | 点「一键修复」（需要能访问 pip 源；内网请让 IT 预装 `playwright` 包） |
| 任务停在「请登录」 | 在弹出的 Chrome 里登录，回来点「我已登录，继续」 |
| 想定时自动跑 | 让 IT 运行 `scripts\windows\Register-ScheduledRun.ps1`（见 `STANDALONE.zh.md`） |
| 公司已经装了 chrome-use 扩展 | 不影响；默认仍用 Playwright。IT 想强制用扩展可设 `UNIVERSAL_BROWSER_ENGINE=chrome-use` |

## 公司有 Skill Hub / Agent

不用解压：在技能市场安装 **Universal Browser**，在 Agent 里输入 **`/universal-browser`** 或「列出浏览器任务」，按提示选任务、填信息；需要登录时在 Chrome 里登录即可。上架步骤见 `SKILL-HUB.zh.md`。

## 我是 IT / 运维

以上默认路径使用 Playwright 驱动用户本机 Chrome（独立登录 Profile 存在技能目录 `runs\chrome-profile`）。
高级选项——附着到已登录 Chrome、指定 Chrome 路径、无头、chrome-use 引擎、内网镜像、定时任务——见 `STANDALONE.zh.md`。
