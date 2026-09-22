# Universal Browser Skill — 快速开始

**没有其它平台、只有 OpenCode + chrome-use 扩展时**：Hub 上传 **[完整技能包 v0.1.5（≤5MB，不含 CLI）](https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.1.5-full/universal-browser-full-0.1.5.zip)**。chrome-use CLI 在机器上单独准备（自动下载、sidecar 或 `CHROME_USE_BIN`）。见 **`docs/STANDALONE.zh.md`**。

**有 Skill Hub + 服务端平台工具时**：可用 slim 包或完整包，见 `docs/SKILL-HUB.zh.md`。

**本地开发（可选）：** `./scripts/install.sh`

---

# Universal Browser Skill

A platform-native Skill package for **template-driven business data automation** (Acquire → Validate → Report → Deliver). Architecture and roadmap: **`docs/PLATFORM-ARCHITECTURE.zh.md`**.

It installs into an existing Agent platform, uses that platform's chrome-use tool/plugin with the user's signed-in Chrome, treats
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
