# 完整 Skill 包说明（runtime + templates）

本目录与 `SKILL.md` 同属 **universal-browser** 技能根目录。标准 Skill 规范允许在技能目录下附带 `references/`、`scripts/`、`assets/` 等；此处用 **`templates/`** 与 **`runtime/`** 把执行层与模板一并交付。

## 目录

| 路径 | 内容 |
|------|------|
| `SKILL.md` | Agent 编排说明（标准 Skill） |
| `references/` | 模板 schema、Runbook |
| `templates/` | 版本化任务模板（YAML） |
| `runtime/` | Python 包 `universal-browser-skill` 源码（`pip install` 用） |

## 平台一次性安装（Worker / Agent 服务端）

在技能解压目录下执行：

```bash
pip install ./runtime
```

依赖：Python **3.12+**，以及你们已有的 **chrome-use** 工具。

## 代码里如何指向本包路径

```python
from pathlib import Path
from browser_skill.app import BrowserSkillApp
from browser_skill.browser.chrome_use import ChromeUseToolAdapter

SKILL_ROOT = Path("/path/to/universal-browser")  # Hub 解压后的技能目录

app = BrowserSkillApp(
    templates_root=SKILL_ROOT / "templates",
    runs_root=Path("/var/agent/runs"),  # 按租户/用户分子目录
    adapter=ChromeUseToolAdapter(your_chrome_use_invoke),
)
```

## 与「仅 SKILL.md 的包」对比

- **标准小包**（`universal-browser-0.1.2.zip`）：只有 `SKILL.md` + `references/`，适合 Hub 只分发指令、运行时由平台统一部署。
- **完整包**（`universal-browser-full-0.1.2.zip`）：本说明 + `templates/` + `runtime/` + `scripts/`，适合 Hub **一个 ZIP 搞定** 指令与执行层（含 Windows 首次自动下载 chrome-use CLI）。

chrome-use 仍在用户 Chrome / 平台插件侧，无法打入 ZIP。
