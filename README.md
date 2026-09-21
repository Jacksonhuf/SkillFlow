# Universal Browser Skill — 快速开始

**一条命令安装** → 在 Agent 里 **`/universal-browser`** 使用。

```bash
git clone https://github.com/Jacksonhuf/SkillFlow.git && cd SkillFlow
./scripts/install.sh
```

中文步骤见 **[docs/QUICKSTART.zh.md](docs/QUICKSTART.zh.md)**。

---

# Universal Browser Skill

A platform-native Skill package for template-driven browser tasks. It installs into an existing
Agent platform, uses that platform's chrome-use tool/plugin with the user's signed-in Chrome, treats
downloads as first-class outputs, and reports success only after business-result validation.

It is **not** an Agent platform, standalone chat application, browser automation service, or end-user
CLI. The host platform owns conversation, identity, model access, sessions, file delivery, user
confirmation, and UI rendering.

## Simple install (OpenCode / standard skills)

```bash
./scripts/install.sh              # project: .opencode/skills + .agents/skills
./scripts/install.sh --global     # machine-wide: ~/.config/opencode/skills
browser-skill setup               # same as the skill-directory step after pip install
```

Then in Agent chat: **`/universal-browser`** or ask to list browser task templates.

## Integration outline
