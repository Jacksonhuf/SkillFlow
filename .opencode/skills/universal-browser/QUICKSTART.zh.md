# Universal Browser — 3 分钟上手

面向 **OpenCode 内核 / 标准 Skill** 的自研 Agent。你不需要先读架构文档。

## 第一步：一键安装

在仓库根目录执行（只需一次）：

```bash
git clone https://github.com/Jacksonhuf/SkillFlow.git
cd SkillFlow
./scripts/install.sh
```

脚本会自动：

- 创建 Python 虚拟环境并安装本 Skill 运行时（`browser-skill` 命令）
- 把 **标准 Skill** 安装到 `.opencode/skills/` 和 `.agents/skills/`（OpenCode 会自动发现）
- 可选：加 `--global` 装到本机所有项目（`~/.config/opencode/skills/`）

等价命令：

```bash
./scripts/install.sh --global
python -m browser_skill.setup   # 若已 pip install，可单独重装 Skill 目录
browser-skill setup --global
```

## 第二步：在 Agent 里使用（业务用户）

1. 用 **OpenCode / 自研 Agent** 打开 **SkillFlow 仓库** 或已执行过安装的工程目录。  
2. 在对话里输入：
   - **`/universal-browser`**，或  
   - **「列出浏览器任务 / 选择模板跑任务」**  
3. 按 Agent 提示选模板、填变量；若要登录，在 **Chrome** 里完成 SSO/MFA，再在 Agent 里点 **继续任务**。

Skill 文件位置（安装后）：

```text
.opencode/skills/universal-browser/SKILL.md
.agents/skills/universal-browser/SKILL.md
```

## 第三步：平台必须有的东西（管理员一次性配置）

| 能力 | 谁负责 | 说明 |
|------|--------|------|
| **chrome-use 插件** | 你们平台（已有） | 用户 Chrome 已登录业务系统 |
| **Skill 指令** | `./scripts/install.sh` | 教 Agent 怎么编排任务 |
| **Python 运行时** | 同上脚本 | 真正执行模板、写结果；平台需能调用 `BrowserSkillApp` 或提供等价工具 |

若 Agent **只会读 Skill、还没有接 Python 工具**，用户只能看到「该怎么跑」的说明，**还不能自动抓数**。需要平台同事接一行 invoker（见 `docs/QUICKSTART.zh.md` 里的「管理员」小节或 `examples/opencode_minimal_tool.py`）。

## 维护者自检（可选）

```bash
source .venv/bin/activate
browser-skill templates      # 看有哪些模板
browser-skill doctor         # 检查本机 chrome-use CLI（可选）
```

## 常见问题

**Q：Skill 装了但 Agent 说找不到？**  
确认 Agent 工作区是执行过 `install.sh` 的目录，或使用了 `--global` 且 OpenCode 扫描 `~/.config/opencode/skills/`。

**Q：和 clone 整个仓库有什么区别？**  
OpenCode 只加载 `universal-browser/SKILL.md` 目录；`install.sh` 帮你复制到标准路径并装好 Python。

**Q：模板 URL 是 example.internal？**  
示例模板需改成你们内网地址，或用 Teach 创建新模板（见 `SKILL.md` 工作流）。

更多细节见 `README.md`、`docs/requirements.md`。
