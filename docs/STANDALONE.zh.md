# 独立模式：只有 OpenCode Agent + chrome-use（无其它平台）

适用：**没有自研 Agent 工具链**，只有 Skill Hub / OpenCode 技能 + 本机 **chrome-use 扩展与 CLI**。

## 用哪个包

下载 **完整包**（不要下 slim 包）：

https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.1.0-full/universal-browser-full-0.1.0.zip

解压后得到 `universal-browser/`，上传到 Skill Hub 或放到 OpenCode 技能目录。

## 目录里有什么（除 chrome-use 外全在这里）

```text
universal-browser/
├── SKILL.md          # Agent 读的操作说明
├── references/
├── templates/        # 任务模板
├── runtime/          # Python 执行引擎源码
├── scripts/
│   ├── invoke.py     # 直接跑任务（无需 pip install 到系统）
│   └── setup.sh      # 可选：pip install ./runtime
└── RUNTIME.zh.md
```

**唯一外部依赖**：本机 [chrome-use 扩展](https://chromewebstore.google.com/detail/chrome-use/knfcmbamhjmaonkfnjhldjedeobeafmk) + 对应的 **chrome-use CLI** 在 PATH 里，且 Chrome 已登录业务系统。

## Agent 怎么执行（OpenCode）

1. 加载技能 `universal-browser`（`/universal-browser`）。  
2. 需要真正跑浏览器时，在技能目录下执行（Agent 用终端工具）：

```bash
python3 scripts/invoke.py doctor
python3 scripts/invoke.py templates
python3 scripts/invoke.py start
python3 scripts/invoke.py run inventory_feedback --var date=2026-09-20
python3 scripts/invoke.py resume <run_id>
```

输出为 JSON（含 `interaction`、artifacts 路径），Agent 读结果继续对话。

3. 环境变量（可选）：

```bash
export UNIVERSAL_BROWSER_SKILL_ROOT=/path/to/universal-browser
```

## 用户只做两件事

1. 安装 chrome-use 扩展并保持 Chrome 登录。  
2. 在 Agent 里启用本技能，按提示让 Agent 调用 `scripts/invoke.py` 或自行在终端运行上述命令。

不需要：单独平台、SkillFlow git clone、`install.sh`（除非本地开发仓库本身）。
